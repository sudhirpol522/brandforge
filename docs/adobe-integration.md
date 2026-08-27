# Adobe integration

OpenAI is the primary provider selected for this build. Adobe remains the product-specific editing
and optional image-generation path.

## Firefly

Set ADOBE_FIREFLY_ENABLED=true and configure the server-side Firefly client ID and secret. The
adapter obtains an IMS client-credentials token and calls the v3 generate-image endpoint. Never
expose the Firefly client secret to Next.js.

The current adapter is credential-dependent and has not been exercised in the packaged
environment. Production must use the asynchronous endpoint, persist job IDs, poll with bounded
backoff, cancel abandoned jobs, and ingest successful output into private storage immediately.

Official references:

- [Firefly authentication](https://developer.adobe.com/firefly-services/docs/firefly-api/getting-started/)
- [Generate Image API](https://developer.adobe.com/firefly-services/docs/firefly-api/guides/how-tos/firefly-generate-image-api-tutorial)
- [Asynchronous Firefly APIs](https://developer.adobe.com/firefly-services/docs/firefly-api/guides/how-tos/using-async-apis)

## Adobe Express

The completed UI contains a feature-flagged Express v4 handoff. Configure:

- NEXT_PUBLIC_ADOBE_EXPRESS_ENABLED=true
- NEXT_PUBLIC_ADOBE_EXPRESS_CLIENT_ID
- NEXT_PUBLIC_ADOBE_EXPRESS_APP_NAME

The Express client ID is browser-visible by design; restrict it to exact HTTPS domains in Adobe
Developer Console. The OpenAI and Firefly secrets remain server-only.

As of July 2026, new Adobe Express Embed SDK access requires business approval. Local and
production integrations also require HTTPS. Until credentials and approval are available, the
button explains that it is not configured and the editable SVG export remains usable.

Official references:

- [Express Embed SDK overview](https://developer.adobe.com/express/embed-sdk/docs/guides/)
- [Full editor tutorial](https://developer.adobe.com/express/embed-sdk/docs/guides/tutorials/full-editor)
- [Submission and review](https://developer.adobe.com/express/embed-sdk/docs/guides/review/)

## Export contract

BrandForge exports one SVG per channel and a manifest containing the selected variant, agent graph,
prompt/model versions, brand-rule version, input hashes, approval IDs, estimated cost, and file
keys. Express is an editing surface; BrandForge remains the approval and provenance system.
