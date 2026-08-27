"use client";

import { useRef, useState } from "react";

declare global {
  interface Window {
    CCEverywhere?: {
      initialize: (
        host: { clientId: string; appName: string },
        config?: Record<string, unknown>
      ) => Promise<Record<string, unknown>>;
    };
    BrandForgeAdobeExpressSdk?: Promise<Record<string, unknown>>;
  }
}

const SDK_URL = "https://cc-embed.adobe.com/sdk/v4/CCEverywhere.js";

function loadSdk(): Promise<void> {
  if (window.CCEverywhere) return Promise.resolve();
  return new Promise((resolve, reject) => {
    const existing = document.querySelector<HTMLScriptElement>(`script[src="${SDK_URL}"]`);
    const script = existing ?? document.createElement("script");
    const onLoad = () => {
      if (window.CCEverywhere) resolve();
      else reject(new Error("Adobe Express SDK loaded but did not initialize"));
    };
    const onError = () => reject(new Error("Adobe Express SDK could not be loaded"));

    script.addEventListener("load", onLoad, { once: true });
    script.addEventListener("error", onError, { once: true });
    if (!existing) {
      script.src = SDK_URL;
      script.async = true;
      document.head.appendChild(script);
    }
  });
}

function initializeSdk(clientId: string, appName: string): Promise<Record<string, unknown>> {
  if (!window.BrandForgeAdobeExpressSdk) {
    window.BrandForgeAdobeExpressSdk = loadSdk()
      .then(() => window.CCEverywhere!.initialize({ clientId, appName }, {}))
      .catch((error) => {
        delete window.BrandForgeAdobeExpressSdk;
        throw error;
      });
  }
  return window.BrandForgeAdobeExpressSdk;
}

export function AdobeExpressButton({
  imageUrl,
  assetBlob
}: {
  imageUrl: string;
  assetBlob?: Blob | null;
}) {
  const [message, setMessage] = useState("");
  const [opening, setOpening] = useState(false);
  const openingRef = useRef(false);
  const enabled = process.env.NEXT_PUBLIC_ADOBE_EXPRESS_ENABLED === "true";
  const clientId = process.env.NEXT_PUBLIC_ADOBE_EXPRESS_CLIENT_ID ?? "";
  const appName = process.env.NEXT_PUBLIC_ADOBE_EXPRESS_APP_NAME ?? "BrandForge";

  async function openEditor() {
    if (openingRef.current) return;
    if (!enabled || !clientId) {
      setMessage("Configure the Express client ID and an HTTPS allowed domain first.");
      return;
    }
    openingRef.current = true;
    setOpening(true);
    try {
      setMessage("Opening Adobe Express…");
      let asset = assetBlob;
      if (!asset) {
        const assetResponse = await fetch(imageUrl);
        if (!assetResponse.ok) throw new Error("The campaign visual could not be loaded");
        asset = await assetResponse.blob();
      }
      if (!asset.size || !asset.type.toLowerCase().startsWith("image/")) {
        throw new Error("The selected campaign asset is not a valid image");
      }
      const sdk = await initializeSdk(clientId, appName);
      const editor = sdk.editor as {
        createWithAsset?: (docConfig: Record<string, unknown>) => void | Promise<void>;
      };
      if (!editor?.createWithAsset) throw new Error("Full editor is unavailable for this credential");
      await editor.createWithAsset({
        asset: {
          name: "BrandForge campaign visual",
          type: "image",
          dataType: "blob",
          data: asset
        }
      });
      setMessage("");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Adobe Express could not open");
    } finally {
      openingRef.current = false;
      setOpening(false);
    }
  }

  return (
    <div>
      <button className="button secondary" type="button" onClick={openEditor} disabled={opening}>
        {opening ? "Opening Adobe Express…" : "Open in Adobe Express"}
      </button>
      {message && <p className="microcopy" role="status">{message}</p>}
    </div>
  );
}
