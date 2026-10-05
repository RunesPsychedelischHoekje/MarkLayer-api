# MarkLayer API: Terms of Use

_Last updated: October 5, 2026_

These terms apply to your use of the MarkLayer API ("the API"). They add to the RapidAPI Terms of Service, which govern your account, subscription, billing, and refunds. By subscribing to or calling the API, you agree to these terms.

## 1. The service
MarkLayer adds machine-readable provenance markings to images (a signed C2PA manifest, an invisible TrustMark watermark, and IPTC metadata), reports the provenance signals found in files you submit, and tests how markings survive common edits.

## 2. Not legal advice; no compliance certificate
**MarkLayer provides technical marking and inspection tools. It is not legal advice and does not certify compliance** with the EU AI Act, California's AI Transparency Act, or any other law. Whether and how you must mark or label content depends on your role (provider, deployer), your product, and the jurisdictions you serve. You remain responsible for your own compliance, including documenting your approach, disclosing AI use to people where the law requires it, and choosing the right `kind` for each image.

## 3. Limits of the technology
- **Metadata layers do not survive re-encoding.** Most social platforms, messaging apps and screenshots remove C2PA and IPTC metadata. The watermark is designed to survive common edits, but heavy cropping, some colour edits, and deliberate removal attempts can defeat it. No marking technique is tamper-proof.
- **Signer trust.** Manifests are signed with MarkLayer's certificate. Until MarkLayer is on the C2PA trust list, verifiers show the signature as valid but the signer as not recognised. The `/health` endpoint shows the current status.
- **Inspection reports evidence, not truth.** `/v1/inspect` reports signals that are present in a file. It does not determine whether content is AI-generated. A result of `no_signals` does not mean the content was made by a human, and unsigned metadata can be forged.

## 4. Data handling
- **Files are processed in memory and not stored.** We do not keep copies of images or files you upload or that we download for you, nor of the marked results. Receipts are generated per request and not retained by us: keep the receipt if you need it for your records.
- **What the marks contain.** The C2PA manifest records the action ("created"), the digital source type, the `generator` name you supply, and MarkLayer as signer. The watermark carries a random identifier, not personal data. Do not put personal data in `generator`.
- **Operational logs.** Our hosting provider records request metadata: time, endpoint, status code, response time, network address and the request URL. For `GET /v1/inspect`, the URL you submit is part of the request URL and so appears in these logs.
- **URLs you submit.** For URL inspection we download the file from the address you give. The site you point us to sees the request coming from our servers.
- **Location.** The API is hosted by Render in the EU (Frankfurt). RapidAPI processes your requests as a proxy under its own privacy policy.
- Images can contain personal data (for example, faces). You confirm you have a lawful basis to submit them. To the extent we process personal data on your behalf, we do so only to provide the service.

## 5. Your responsibilities
- Submit only content you have the right to process and mark.
- Do not use the API to mark content in a misleading way, for example by marking human-made content as AI-generated to discredit it, or by marking content to impersonate another organisation's provenance.
- Do not attempt to bypass RapidAPI, exceed your plan's rate limits by technical means, or overload the service.
- Do not use URL inspection to probe networks or systems you are not authorised to access.

## 6. Availability and changes
- The API is provided "as is" and "as available", with no uptime or service-level guarantee.
- Endpoints under `/v1` will not have breaking changes without at least 30 days' notice on the RapidAPI listing. We may add new optional fields or endpoints at any time.
- We may update the trust lists and generator fingerprints used by `/v1/inspect`, which can change results for the same file over time.

## 7. Limitation of liability
To the maximum extent permitted by law, the provider is not liable for indirect, incidental, or consequential damages, or for losses arising from reliance on markings or inspection results, including regulatory fines, content-moderation decisions, or disputes about the origin of content. Total liability for any claim is limited to the amount you paid for the API in the 3 months before the claim.

## 8. Suspension
We may suspend access for violations of these terms, abuse, or activity that threatens the service's stability or other users.

## 9. Changes to these terms
We may update these terms. Material changes will be announced on the RapidAPI listing. Continuing to use the API after a change means you accept the updated terms.

## 10. Contact
Questions: use the Discussions tab on the RapidAPI listing, or email propeneprop@gmail.com.

## Acknowledgements
Watermarking uses Adobe's TrustMark models and error-correction code (MIT licence). C2PA trust lists come from the C2PA conformance programme and contentcredentials.org.
