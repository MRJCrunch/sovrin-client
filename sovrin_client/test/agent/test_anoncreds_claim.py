from sovrin_client.test import waits
from stp_core.loop.eventually import eventually
from anoncreds.protocol.types import SchemaKey, ID
from anoncreds.protocol.utils import crypto_int_to_str


def test_claim_from_libsovrin_works(aliceAgent, aliceAcceptedFaber, aliceAcceptedAcme,
                  acmeAgent, emptyLooper):
    faberLink = aliceAgent.wallet.getLink('Faber College')
    name, version, origin = faberLink.availableClaims[0]
    schemaKey = SchemaKey(name, version, origin)
    timeout = waits.expectedClaimsReceived()

    async def create_claim_and_send_to_prover():
        claimReq = await aliceAgent.prover.createClaimRequest(
            schemaId=ID(schemaKey),
            proverId='b1134a647eb818069c089e7694f63e6d',
            reqNonRevoc=False)

        assert claimReq

        msg = ({'type': 'CLAIM', 'refRequestId': 1498207862797639, 'data': {'revoc_ref_seq_no': 0,
                                                                            'claim': '{"ssn": ["123-45-6789", "744326867119662813058574151710572260086480987778735990385444735594385781152"], "student_name": ["Alice Garcia", "42269428060847300013074105341288624461740820166347597208920185513943254001053"], "year": ["2015", "76155730627064255622230347398579434243999717245284701820698087443021519005597"], "status": ["graduated", "79954080701401061138041003494589205197191732193019334789897013390726508263804"], "degree": ["Bachelor of Science, Marketing", "111351644242834420607747624840774158853435703856237568018084128306949040580032"]}',
                                                                            'schema_seq_no': 13, 'claim_def_seq_no': 14,
                                                                            'identifier': 'FuN98eH2eZybECWkofW6A9BKJxxnTatBCopfUiNxo6ZB',
                                                                            'claims_signature': {'nonRevocClaim': None,
                                                                                                 'primaryClaim': {
                                                                                                     'm2': '22785022781642864732319986532825092093225083052430746779069605227319570029381',
                                                                                                     'e': '259344723055062059907025491480697571938277889515152306249728583105665800713306759149981690559193987143012367913206299323899696942213235956742929792153461185966536098746467972473109',
                                                                                                     'v': '7629729863453258305592512142617673266706553002136669184455436940340194236628242182218956392824009393530261968156940878240620599399119866901759277398381559228013423412833813963098623377559871542242498593970775333374424846432332515335673542919592159864583522140462129862791672425903379872632832577501865009739503061813380591602165174007269011059027477030725265250653234874322854858681623060998369705769757266527877637694180951086777421728002089105115984825372641042599669631455780213815764726629752037530155205242558754705763077632003116450220509322290689690298568824882937187535637595196213028332830611475451582303322796166423474055303821081316125475360279715699299024415284996080529790195933535778551749430986485696816815990363849007354656762434255588403400248771999851207250608362257486426341717428465175085797666090322',
                                                                                                     'a': '36501610954355587802320346809842827314908107479881876857910399281313722794103253965730802703473849834140704588893331106157038070473605083161340196073271871644491530414629485934942118013644743759861707840114686916033231796927246514308532723306225159544822226399176479812860381848516844809234798544977987979863572869022605213720693556124085657923953897272408251825716801379520931334115557633998253136062987805350602442386382795702029002363772619350981180379699457120993111041079641201791524538183089660117345954208195114115627567081788098553009470374663625652357647189410488892877795487924750104626963098805149915312469'}}},
                'reqId': 1498207879197729,
                'signature': '3v4CJnCpFv3on9DJKzourd9RfvX3gz5yXY1jkhxc8FktHVbvx1ghBJC7DUYMAJzApPUAYMyTzyMB6Dm8HEzhAtvM',
                'identifier': 'FuN98eH2eZybECWkofW6A9BKJxxnTatBCopfUiNxo6ZB'}, ('Faber College', ('127.0.0.1', 6918)))

        await aliceAgent.handleReqClaimResponse(msg)

        # msg = (
        #     {
        #         'issuer_did': 'FuN98eH2eZybECWkofW6A9BKJxxnTatBCopfUiNxo6ZB',
        #         'claim_def_seq_no': 14,
        #         'blinded_ms': {
        #             'prover_did': 'b1134a647eb818069c089e7694f63e6d',
        #             'u': str(crypto_int_to_str(claimReq.U)),
        #             'ur': None
        #         },
        #         'type': 'CLAIM_REQUEST',
        #         'schema_seq_no': 13,
        #         'nonce': 'b1134a647eb818069c089e7694f63e6d',
        #     }
        # )
        #
        # aliceAgent.signAndSendToLink(msg=msg, linkName=faberLink.name)

    emptyLooper.run(eventually(create_claim_and_send_to_prover, timeout=timeout))

    # 2. check that claim is received from Faber
    async def chkClaims():
        claim = await aliceAgent.prover.wallet.getClaimSignature(ID(schemaKey))
        assert claim.primaryClaim

    emptyLooper.run(eventually(chkClaims, timeout=timeout))

    # 3. send proof to Acme
    acme_link, acme_proof_req = aliceAgent.wallet.getMatchingLinksWithProofReq(
        "Job-Application", "Acme Corp")[0]
    aliceAgent.sendProof(acme_link, acme_proof_req)

    # 4. check that proof is verified by Acme
    def chkProof():
        internalId = acmeAgent.get_internal_id_by_nonce(acme_link.invitationNonce)
        link = acmeAgent.wallet.getLinkBy(internalId=internalId)
        assert "Job-Application" in link.verifiedClaimProofs

    timeout = waits.expectedClaimsReceived()
    emptyLooper.run(eventually(chkProof, timeout=timeout))
