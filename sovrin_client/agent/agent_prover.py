import asyncio
import json
from typing import Any
from collections import OrderedDict

from plenum.common.constants import NONCE, TYPE, IDENTIFIER, DATA
from plenum.common.types import f
from plenum.common.util import getCryptonym

from anoncreds.protocol.prover import Prover
from anoncreds.protocol.types import SchemaKey, ID, Claims, ProofInput, AttributeValues
from sovrin_client.agent.msg_constants import CLAIM_REQUEST, PROOF, CLAIM_FIELD, \
    CLAIM_REQ_FIELD, PROOF_FIELD, REVEALED_ATTRS_FIELD, \
    REQ_AVAIL_CLAIMS, ISSUER_DID, CLAIM_DEF_SEQ_NO, CLAIMS_SIGNATURE_FIELD, SCHEMA_SEQ_NO, PROOF_REQUEST_FIELD
from sovrin_client.client.wallet.types import ProofRequest
from sovrin_client.client.wallet.link import Link
from sovrin_common.exceptions import LinkNotReady


class AgentProver:
    def __init__(self, prover: Prover):
        self.prover = prover

    def sendRequestForAvailClaims(self, link: Link):
        if self.loop.is_running():
            self.loop.call_soon(asyncio.ensure_future,
                                self.sendRequestForAvailClaimsAsync(link))
        else:
            self.loop.run_until_complete(
                self.sendRequestForAvailClaimsAsync(link))

    async def sendRequestForAvailClaimsAsync(self, link: Link):
        op = {
            TYPE: REQ_AVAIL_CLAIMS,
            NONCE: link.invitationNonce
        }
        try:
            self.signAndSendToLink(msg=op, linkName=link.name)
        except LinkNotReady as ex:
            self.notifyMsgListener(str(ex))

    def sendReqClaim(self, link: Link, schemaKey):
        if self.loop.is_running():
            self.loop.call_soon(asyncio.ensure_future,
                                self.send_claim(link, schemaKey))
        else:
            self.loop.run_until_complete(
                self.send_claim(link, schemaKey))

    # async def send_claim(self, link, claim_to_request):
    #     return await self.sendReqClaimAsync(link, claim_to_request)

    async def send_claim(self, link: Link, schema_key):
        name, version, origin = schema_key
        schema_key = SchemaKey(name, version, origin)

        claimReq = await self.prover.createClaimRequest(
            schemaId=ID(schema_key),
            proverId=link.invitationNonce,
            reqNonRevoc=False)

        # TODO link.invitationNonce should not be used here.
        # It has served its purpose by this point. Claim Requests do not need a nonce.
        public_key = await self.prover.wallet.getPublicKey(ID(schema_key))
        schema = await self.prover.wallet.getSchema(ID(schema_key))

        claimRequestDetails = {
            SCHEMA_SEQ_NO: schema.seqId,
            ISSUER_DID: origin,
            CLAIM_DEF_SEQ_NO: public_key.seqId,
            CLAIM_REQ_FIELD: claimReq.to_str_dict()
        }

        op = {
            TYPE: CLAIM_REQUEST,
            NONCE: link.invitationNonce,
            DATA: claimRequestDetails
        }

        self.signAndSendToLink(msg=op, linkName=link.name)

    def handleProofRequest(self, msg):
        body, _ = msg
        link = self._getLinkByTarget(getCryptonym(body.get(IDENTIFIER)))
        proofRequest = body.get(PROOF_REQUEST_FIELD)
        proofRequest = ProofRequest.from_str_dict(proofRequest)
        proofReqName = proofRequest.name
        proofReqExist = False

        for request in link.proofRequests:
            if request.name == proofReqName:
                proofReqExist = True
                break

        self.notifyMsgListener('    Proof request {} received from {}.\n'
                               .format(proofReqName, link.name))

        if not proofReqExist:
            link.proofRequests.append(proofRequest)
        else:
            self.notifyMsgListener('    Proof request {} already exist.\n'
                                   .format(proofReqName))

    async def handleReqClaimResponse(self, msg):
        body, _ = msg
        issuerId = body.get(IDENTIFIER)
        claim = body[DATA]
        li = self._getLinkByTarget(getCryptonym(issuerId))
        if li:
            self.notifyResponseFromMsg(li.name, body.get(f.REQ_ID.nm))

            schemaId = ID(schemaId=claim[SCHEMA_SEQ_NO])

            pk = await self.prover.wallet.getPublicKey(schemaId)

            claims = {k: AttributeValues.from_str_dict(v) for k, v in json.loads(claim[CLAIM_FIELD]).items()}
            signature = Claims.from_str_dict(claim[CLAIMS_SIGNATURE_FIELD], pk.N)

            await self.prover.processClaim(schemaId, claims, signature)
        else:
            self.notifyMsgListener("No matching link found")

    def sendProof(self, link: Link, proofReq: ProofRequest):
        if self.loop.is_running():
            self.loop.call_soon(asyncio.ensure_future,
                                self.sendProofAsync(link, proofReq))
        else:
            self.loop.run_until_complete(self.sendProofAsync(link, proofReq))

    async def sendProofAsync(self, link: Link, proofRequest: ProofRequest):
        # TODO _F_ this nonce should be from the Proof Request, not from an
        # invitation
        proofInput = ProofInput(nonce=int(proofRequest.nonce),
                                revealedAttrs=proofRequest.verifiableAttributes,
                                predicates=proofRequest.predicates)
        # TODO rename presentProof to buildProof or generateProof

        proof = await self.prover.presentProof(proofInput)
        proof.requestedProof.self_attested_attrs.update(proofRequest.selfAttestedAttrs)
        op = OrderedDict([
            (TYPE, PROOF),
            (NONCE, link.invitationNonce),
            (PROOF_FIELD, proof.to_str_dict()),
            (PROOF_REQUEST_FIELD, proofRequest.to_str_dict()),
            # TODO _F_ why do we need to send this? isn't the same data passed as keys in 'proof'?
            (REVEALED_ATTRS_FIELD,
             json.dumps({k: v.to_str_dict() for k, v in proofRequest.verifiableAttributes.items()}))
        ])

        self.signAndSendToLink(msg=op, linkName=link.name)

    def handleProofStatusResponse(self, msg: Any):
        body, _ = msg
        data = body.get(DATA)
        identifier = body.get(IDENTIFIER)
        li = self._getLinkByTarget(getCryptonym(identifier))
        self.notifyResponseFromMsg(li.name, body.get(f.REQ_ID.nm))
        self.notifyMsgListener(data)

    async def getMatchingLinksWithReceivedClaimAsync(self, claimName=None):
        matchingLinkAndAvailableClaim = self.wallet.getMatchingLinksWithAvailableClaim(
            claimName)
        matchingLinkAndReceivedClaim = []
        for li, cl in matchingLinkAndAvailableClaim:
            name, version, origin = cl
            schemaKeyId = ID(
                SchemaKey(name=name, version=version, issuerId=origin))
            schema = await self.prover.wallet.getSchema(schemaKeyId)
            claimAttrs = OrderedDict()
            for attr in schema.attrNames:
                claimAttrs[attr] = None
            attrs = None
            try:
                attrs = await self.prover.wallet.getClaim(schemaKeyId)
            except ValueError:
                pass  # it means no claim was issued

            if attrs:
                if set(claimAttrs.keys()).intersection(attrs.keys()):
                    for k in claimAttrs.keys():
                        claimAttrs[k] = attrs[k].raw
            matchingLinkAndReceivedClaim.append((li, cl, claimAttrs))
        return matchingLinkAndReceivedClaim

    async def getMatchingRcvdClaimsAsync(self, attributes):
        linksAndReceivedClaim = await self.getMatchingLinksWithReceivedClaimAsync()
        attributes = set(attributes)

        matchingLinkAndRcvdClaim = []
        for li, cl, issuedAttrs in linksAndReceivedClaim:
            if attributes.intersection(issuedAttrs.keys()):
                matchingLinkAndRcvdClaim.append((li, cl, issuedAttrs))
        return matchingLinkAndRcvdClaim

    async def getClaimsUsedForAttrs(self, attributes):
        allMatchingClaims = await self.getMatchingLinksWithReceivedClaimAsync()
        alreadySatisfiedKeys = {}
        claimsToUse = []
        alreadyAddedClaims = []

        for li, cl, issuedAttrs in allMatchingClaims:
            issuedClaimKeys = issuedAttrs.keys()
            for key in attributes.keys():
                if key not in alreadySatisfiedKeys and key in issuedClaimKeys:
                    if li not in alreadyAddedClaims:
                        claimsToUse.append((li, cl, issuedAttrs))
                    alreadySatisfiedKeys[key] = True
                    alreadyAddedClaims.append(li)

        return claimsToUse
