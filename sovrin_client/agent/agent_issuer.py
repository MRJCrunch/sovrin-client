from abc import abstractmethod
from typing import Dict, Any

from plenum.common.constants import NAME, VERSION, ORIGIN
from plenum.common.types import f

from anoncreds.protocol.issuer import Issuer
from anoncreds.protocol.types import SchemaKey, ID
from anoncreds.protocol.types import ClaimRequest
from sovrin_client.agent.constants import EVENT_NOTIFY_MSG, CLAIMS_LIST_FIELD
from sovrin_client.agent.msg_constants import CLAIM, CLAIM_REQ_FIELD, CLAIM_FIELD, \
    AVAIL_CLAIM_LIST, CLAIM_DEF_SEQ_NO, REVOC_REG_SEQ_NO, CLAIMS_SIGNATURE_FIELD, SCHEMA_SEQ_NO
from sovrin_common.identity import Identity

from sovrin_client.client.wallet.attribute import Attribute


class AgentIssuer:
    def __init__(self, issuer: Issuer):
        self.issuer = issuer

    async def processReqAvailClaims(self, msg):
        body, (frm, ha) = msg
        link = self.verifyAndGetLink(msg)
        data = {
            CLAIMS_LIST_FIELD: self.get_available_claim_list(link)
        }
        resp = self.getCommonMsg(AVAIL_CLAIM_LIST, data)
        self.signAndSend(resp, link.localIdentifier, frm)

    async def processReqClaim(self, msg):
        body, (frm, _) = msg
        link = self.verifyAndGetLink(msg)
        if not link:
            raise NotImplementedError

        schemaId = ID(schemaId=body[SCHEMA_SEQ_NO])
        schema = await self.issuer.wallet.getSchema(schemaId)

        if not self.is_claim_available(link, schema.name):
            self.notifyToRemoteCaller(
                EVENT_NOTIFY_MSG, "This claim is not yet available.",
                self.wallet.defaultId, frm,
                origReqId=body.get(f.REQ_ID.nm))
            return

        public_key = await self.issuer.wallet.getPublicKey(schemaId)
        claimReq = ClaimRequest.from_str_dict(body[CLAIM_REQ_FIELD], public_key.N)

        schemaKey = SchemaKey(schema.name, schema.version, schema.issuerId)
        self._add_attribute(schemaKey=schemaKey, proverId=claimReq.userId,
                            link=link)

        (signature, claim) = await self.issuer.issueClaim(schemaId, claimReq)

        claimDetails = {
            CLAIMS_SIGNATURE_FIELD: signature.to_str_dict(),
            f.IDENTIFIER.nm: schema.issuerId,
            CLAIM_FIELD: str(claim),
            CLAIM_DEF_SEQ_NO: public_key.seqId,
            REVOC_REG_SEQ_NO: 0,
            SCHEMA_SEQ_NO: schema.seqId
        }

        resp = self.getCommonMsg(CLAIM, claimDetails)
        self.signAndSend(resp, link.localIdentifier, frm,
                         origReqId=body.get(f.REQ_ID.nm))

    def _add_attribute(self, schemaKey, proverId, link):
        attr = self.issuer_backend.get_record_by_internal_id(link.internalId)
        self.issuer._attrRepo.addAttributes(schemaKey=schemaKey,
                                            userId=proverId,
                                            attributes=attr)

    def publish_trust_anchor(self, idy: Identity):
        self.wallet.addTrustAnchoredIdentity(idy)
        reqs = self.wallet.preparePending()
        self.client.submitReqs(*reqs)

    def publish_trust_anchor_attribute(self, attrib: Attribute):
        self.wallet.addAttribute(attrib)
        reqs = self.wallet.preparePending()
        self.client.submitReqs(*reqs)