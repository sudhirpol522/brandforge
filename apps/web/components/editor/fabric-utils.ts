import type {
  Canvas,
  FabricImage,
  FabricObject,
  Group,
  TMat2D,
} from "fabric";

import type {
  CanonicalLayer,
  EditorChannel,
  ImageFitMode,
  JsonValue,
  LayerDocument,
  LayerType,
} from "./editor-types";

type FabricModule = typeof import("fabric");
export type EditorObject = FabricObject & {
  id?: string;
  name?: string;
  role?: string;
  imageFitMode?: ImageFitMode;
  assetKey?: string;
  brandLocked?: boolean;
};

const SAFE_ID = /[^A-Za-z0-9_-]+/g;
const TEXT_TYPES = new Set(["text", "textbox", "i-text", "itext"]);
const SUPPORTED = new Set<LayerType>([
  "text",
  "image",
  "rect",
  "ellipse",
  "path",
  "group",
]);

export function safeIdentifier(value: string, fallback: string): string {
  const cleaned = value.trim().replace(SAFE_ID, "-").replace(/^-+|-+$/g, "");
  return (cleaned || fallback).slice(0, 128);
}

export function objectLayerType(object: FabricObject): LayerType {
  const raw = object.type.toLowerCase();
  const type = TEXT_TYPES.has(raw)
    ? "text"
    : raw === "fabricimage"
      ? "image"
      : raw;
  if (!SUPPORTED.has(type as LayerType)) {
    throw new Error(`Unsupported Fabric object type "${object.type}".`);
  }
  return type as LayerType;
}

export function ensureObjectIdentity(
  object: FabricObject,
  index: number,
  used = new Set<string>(),
  preferredId?: string,
): EditorObject {
  const editorObject = object as EditorObject;
  const base = safeIdentifier(preferredId || editorObject.id || "", `layer-${index + 1}`);
  let id = base;
  let suffix = 2;
  while (used.has(id)) id = `${base.slice(0, 118)}-${suffix++}`;
  used.add(id);
  editorObject.id = id;
  editorObject.name =
    editorObject.name?.trim() ||
    `${objectLayerType(object).replace(/^./, (letter) => letter.toUpperCase())} ${index + 1}`;
  return editorObject;
}

export function parseSvgDimensions(
  svg: string,
  fallbackWidth: number,
  fallbackHeight: number,
): { width: number; height: number } {
  const document = new DOMParser().parseFromString(svg, "image/svg+xml");
  if (document.querySelector("parsererror")) throw new Error("The source SVG is not valid XML.");
  const root = document.documentElement;
  const viewBox = root.getAttribute("viewBox")?.trim().split(/[\s,]+/).map(Number);
  const numeric = (value: string | null) => {
    const number = Number.parseFloat(value || "");
    return Number.isFinite(number) && number > 0 ? number : undefined;
  };
  const width = numeric(root.getAttribute("width"));
  const height = numeric(root.getAttribute("height"));
  if (viewBox?.length === 4 && viewBox.every(Number.isFinite)) {
    return { width: viewBox[2] || fallbackWidth, height: viewBox[3] || fallbackHeight };
  }
  return { width: width || fallbackWidth, height: height || fallbackHeight };
}

function jsonValue(value: unknown): JsonValue {
  if (value === undefined || typeof value === "function") return null;
  return JSON.parse(JSON.stringify(value)) as JsonValue;
}

function baseOptions(layer: CanonicalLayer): Record<string, unknown> {
  return {
    ...layer.transform,
    ...layer.appearance,
    id: layer.id,
    name: layer.name,
    role: layer.role,
    imageFitMode: layer.imageFitMode,
    assetKey: layer.assetKey,
    brandLocked: layer.brandLocked,
    selectable: !layer.locked,
    evented: !layer.locked,
    lockMovementX: layer.locked,
    lockMovementY: layer.locked,
    lockRotation: layer.locked,
    lockScalingX: layer.locked,
    lockScalingY: layer.locked,
  };
}

export function serializeObject(object: FabricObject, fallbackIndex = 0): CanonicalLayer {
  const editorObject = ensureObjectIdentity(object, fallbackIndex);
  const type = objectLayerType(object);
  const serialized = object.toObject() as Record<string, unknown>;
  const layer: CanonicalLayer = {
    id: editorObject.id!,
    name: editorObject.name!,
    type,
    role: editorObject.role,
    imageFitMode: editorObject.imageFitMode,
    assetKey: editorObject.assetKey,
    brandLocked: editorObject.brandLocked,
    locked: !object.selectable || !object.evented,
    transform: {
      left: object.left,
      top: object.top,
      width: object.width,
      height: object.height,
      scaleX: object.scaleX,
      scaleY: object.scaleY,
      angle: object.angle,
      skewX: object.skewX,
      skewY: object.skewY,
      flipX: object.flipX,
      flipY: object.flipY,
      originX: String(object.originX),
      originY: String(object.originY),
    },
    appearance: {
      opacity: object.opacity,
      visible: object.visible,
      fill: jsonValue(object.fill),
      stroke: jsonValue(object.stroke),
      strokeWidth: object.strokeWidth,
      strokeDashArray: object.strokeDashArray ? [...object.strokeDashArray] : null,
      shadow: jsonValue(serialized.shadow),
    },
  };

  if (type === "text") {
    layer.text = {
      value: String(serialized.text ?? ""),
      fontFamily: String(serialized.fontFamily ?? "Arial"),
      fontSize: Number(serialized.fontSize ?? 40),
      fontWeight: (serialized.fontWeight as string | number) ?? "normal",
      fontStyle: String(serialized.fontStyle ?? "normal"),
      textAlign: String(serialized.textAlign ?? "left"),
      lineHeight: Number(serialized.lineHeight ?? 1.16),
      charSpacing: Number(serialized.charSpacing ?? 0),
      underline: Boolean(serialized.underline),
      overline: Boolean(serialized.overline),
      linethrough: Boolean(serialized.linethrough),
      editable: serialized.editable !== false,
      direction: String(serialized.direction ?? "ltr"),
      textBackgroundColor: String(serialized.textBackgroundColor ?? ""),
      styles: jsonValue(serialized.styles),
    };
  } else if (type === "image") {
    const image = object as FabricObject & {
      getSrc: () => string;
      crossOrigin?: string | null;
      cropX?: number;
      cropY?: number;
    };
    layer.image = {
      src: image.getSrc(),
      crossOrigin: image.crossOrigin ?? null,
      cropX: image.cropX ?? 0,
      cropY: image.cropY ?? 0,
      filters: jsonValue(serialized.filters),
    };
  } else if (type === "ellipse") {
    layer.radius = {
      rx: Number(serialized.rx ?? object.width / 2),
      ry: Number(serialized.ry ?? object.height / 2),
    };
  } else if (type === "path") {
    layer.path = {
      commands: jsonValue(serialized.path),
      fillRule: String(serialized.fillRule ?? "nonzero"),
    };
  } else if (type === "group") {
    layer.children = (object as Group)
      .getObjects()
      .map((child, index) => serializeObject(child, index));
  }
  return layer;
}

export function serializeLayerDocument(
  canvas: Canvas,
  channel: EditorChannel,
  width: number,
  height: number,
): LayerDocument {
  return {
    schema_version: 1,
    channel,
    width,
    height,
    layers: canvas.getObjects().map((object, index) => serializeObject(object, index)),
  };
}

export async function deserializeLayer(
  fabric: FabricModule,
  layer: CanonicalLayer,
): Promise<FabricObject> {
  const options = baseOptions(layer);
  let object: FabricObject;
  switch (layer.type) {
    case "text":
      if (!layer.text) throw new Error(`Text layer "${layer.name}" has no text data.`);
      object = new fabric.Textbox(layer.text.value, {
        ...options,
        ...layer.text,
        fontStyle: layer.text.fontStyle as "normal" | "italic" | "oblique",
        textAlign: layer.text.textAlign as
          | "left"
          | "center"
          | "right"
          | "justify"
          | "justify-left"
          | "justify-center"
          | "justify-right",
        direction: layer.text.direction as "ltr" | "rtl",
        text: undefined,
        value: undefined,
      } as ConstructorParameters<typeof fabric.Textbox>[1]);
      break;
    case "image":
      if (!layer.image?.src) throw new Error(`Image layer "${layer.name}" has no source.`);
      object = await fabric.FabricImage.fromURL(
        layer.image.src,
        {
          crossOrigin: (layer.image.crossOrigin ?? undefined) as
            | ""
            | "anonymous"
            | "use-credentials"
            | undefined,
        },
        { ...options, cropX: layer.image.cropX, cropY: layer.image.cropY },
      );
      if (Array.isArray(layer.image.filters) && layer.image.filters.length > 0) {
        const image = object as FabricObject & {
          filters: Awaited<ReturnType<typeof fabric.util.enlivenObjects>>;
          applyFilters: () => void;
        };
        image.filters = await fabric.util.enlivenObjects(layer.image.filters);
        image.applyFilters();
      }
      break;
    case "rect":
      object = new fabric.Rect({ ...options, ...layer.radius });
      break;
    case "ellipse":
      object = new fabric.Ellipse({ ...options, ...layer.radius });
      break;
    case "path":
      if (!layer.path) throw new Error(`Path layer "${layer.name}" has no path commands.`);
      object = new fabric.Path(layer.path.commands as never, {
        ...options,
        fillRule: layer.path.fillRule as "nonzero" | "evenodd",
      });
      break;
    case "group": {
      const children = await Promise.all(
        (layer.children || []).map((child) => deserializeLayer(fabric, child)),
      );
      object = new fabric.Group(children, options);
      break;
    }
    default:
      throw new Error(`Unsupported canonical layer type "${String(layer.type)}".`);
  }
  return object;
}

export function assetKeyForSource(source: string): string {
  let hash = 2166136261;
  for (let index = 0; index < source.length; index += 1) {
    hash ^= source.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return `asset-${(hash >>> 0).toString(36)}`;
}

export function applyImageFit(
  image: FabricImage,
  canvas: Pick<Canvas, "getWidth" | "getHeight">,
  mode: ImageFitMode,
): void {
  if (!image.width || !image.height) {
    throw new Error("The selected image has invalid dimensions.");
  }
  const canvasWidth = canvas.getWidth();
  const canvasHeight = canvas.getHeight();
  const scale = mode === "fit"
    ? Math.min(canvasWidth / image.width, canvasHeight / image.height)
    : Math.max(canvasWidth / image.width, canvasHeight / image.height);
  const values: Record<string, unknown> = {
    originX: "center",
    originY: "center",
    scaleX: scale,
    scaleY: scale,
    cropX: 0,
    cropY: 0,
  };
  if (mode !== "crop" || !Number.isFinite(image.left) || !Number.isFinite(image.top)) {
    values.left = canvasWidth / 2;
    values.top = canvasHeight / 2;
  }
  image.set(values);
  (image as EditorObject).imageFitMode = mode;
  image.setCoords();
}

export async function loadBootstrapDesign(
  fabric: FabricModule,
  canvas: Canvas,
  response: {
    fabric_json: Record<string, JsonValue>;
    layer_document: LayerDocument;
    svg: string;
  },
  visualImageUrl?: string,
): Promise<void> {
  const cache = response.fabric_json;
  const hasCache = Object.keys(cache).length > 0;
  const used = new Set<string>();
  if (hasCache) {
    await canvas.loadFromJSON(cache);
    normalizeLoadedLayout(fabric, canvas);
    canvas.getObjects().forEach((object, index) => ensureObjectIdentity(object, index, used));
    normalizeCampaignImages(canvas);
    if (
      visualImageUrl &&
      !canvas.getObjects().some((object) => objectLayerType(object) === "image")
    ) {
      await addVisualImageLayer(fabric, canvas, visualImageUrl, used);
      canvas.sendObjectToBack(canvas.getObjects().at(-1)!);
    }
    return;
  }

  if (response.svg.trim()) {
    const result = await fabric.loadSVGFromString(
      response.svg,
      (element, object) => {
        const preferred = element.getAttribute("id") || element.getAttribute("data-name") || "";
        const preferredName = element.getAttribute("data-name");
        const editorObject = object as EditorObject;
        if (preferred) editorObject.id = safeIdentifier(preferred, `layer-${used.size + 1}`);
        if (preferredName) editorObject.name = preferredName;
      },
    );
    const objects = result.objects
      .filter((object): object is FabricObject => object !== null)
      .map((object) => makeImportedTextEditable(fabric, object));
    labelImportedLayout(objects, canvas.getWidth(), canvas.getHeight());
    constrainSemanticText(objects, canvas.getWidth());
    if (visualImageUrl && !objects.some((object) => objectLayerType(object) === "image")) {
      await addVisualImageLayer(fabric, canvas, visualImageUrl, used);
    }
    objects.forEach((object, index) => ensureObjectIdentity(object, index, used));
    canvas.add(...objects);
    return;
  }

  for (const layer of response.layer_document.layers) {
    canvas.add(await deserializeLayer(fabric, layer));
  }
  normalizeLoadedLayout(fabric, canvas);
  normalizeCampaignImages(canvas);
}

function labelImportedLayout(
  objects: FabricObject[],
  canvasWidth: number,
  canvasHeight: number,
): void {
  const textNames = ["Concept label", "Headline", "Body copy", "CTA label"];
  objects
    .filter((object) => objectLayerType(object) === "text")
    .sort((left, right) => left.top - right.top)
    .forEach((object, index) => {
      const editorObject = object as EditorObject;
      if (!editorObject.name || /^(text(box)?|i-?text|layer)(?:\s|$)/i.test(editorObject.name)) {
        editorObject.name = textNames[index] || `Text ${index + 1}`;
      }
    });

  const rectangles = objects.filter((object) => objectLayerType(object) === "rect");
  const fullCanvas = rectangles.find(
    (object) =>
      object.getScaledWidth() >= canvasWidth * 0.9 &&
      object.getScaledHeight() >= canvasHeight * 0.9,
  );
  if (fullCanvas) {
    const editorObject = fullCanvas as EditorObject;
    editorObject.name ||= "Gradient overlay";
    fullCanvas.set("opacity", Math.min(fullCanvas.opacity, 0.3));
  }
  rectangles
    .filter((object) => object !== fullCanvas)
    .sort(
      (left, right) =>
        right.getScaledWidth() * right.getScaledHeight() -
        left.getScaledWidth() * left.getScaledHeight(),
    )
    .forEach((object, index) => {
      const editorObject = object as EditorObject;
      editorObject.name ||= index === 0 ? "Content panel" : "CTA background";
    });
}

function constrainSemanticText(objects: FabricObject[], canvasWidth: number): void {
  const safeMargin = canvasWidth * 0.05;
  const safeWidth = canvasWidth * 0.9;
  objects.forEach((object) => {
    if (objectLayerType(object) !== "text") return;
    const name = ((object as EditorObject).name || "").toLowerCase();
    if (name !== "headline" && name !== "body copy") return;
    const scaleX = Math.max(Math.abs(object.scaleX), 0.001);
    object.set("width", Math.min(object.width, safeWidth / scaleX));
    if (name === "body copy") object.set("lineHeight", 1.25);
    object.setCoords();
    const bounds = object.getBoundingRect();
    let adjustment = 0;
    if (bounds.left < safeMargin) adjustment = safeMargin - bounds.left;
    if (bounds.left + bounds.width > canvasWidth - safeMargin) {
      adjustment = canvasWidth - safeMargin - (bounds.left + bounds.width);
    }
    if (adjustment) object.set("left", object.left + adjustment);
    object.setCoords();
  });
}

function normalizeLoadedLayout(fabric: FabricModule, canvas: Canvas): void {
  const original = [...canvas.getObjects()];
  original.forEach((object, index) => {
    const replacement = makeImportedTextEditable(fabric, object);
    if (replacement === object) return;
    canvas.remove(object);
    canvas.insertAt(index, replacement);
  });
  const objects = canvas.getObjects();
  labelImportedLayout(objects, canvas.getWidth(), canvas.getHeight());
  constrainSemanticText(objects, canvas.getWidth());
}

function normalizeCampaignImages(canvas: Canvas): void {
  canvas.getObjects().forEach((object) => {
    if (objectLayerType(object) !== "image") return;
    const image = object as FabricImage & EditorObject;
    const isCampaignVisual =
      image.role === "campaign-visual" ||
      image.id === "campaign-visual" ||
      image.name?.toLowerCase() === "campaign visual";
    if (!isCampaignVisual) return;
    image.role = "campaign-visual";
    image.name = "Campaign visual";
    image.assetKey ||= assetKeyForSource(image.getSrc());
    if (!["fit", "fill", "crop"].includes(image.imageFitMode || "")) {
      applyImageFit(image, canvas, "fit");
    }
  });
}

function makeImportedTextEditable(
  fabric: FabricModule,
  object: FabricObject,
): FabricObject {
  if (objectLayerType(object) !== "text" || object instanceof fabric.Textbox) return object;
  const properties = object.toObject([
    "id",
    "name",
    "role",
    "imageFitMode",
    "assetKey",
    "brandLocked",
  ] as never) as Record<string, unknown>;
  const text = String(properties.text ?? "");
  delete properties.type;
  delete properties.version;
  delete properties.text;
  return new fabric.Textbox(
    text,
    properties as ConstructorParameters<typeof fabric.Textbox>[1],
  );
}

async function addVisualImageLayer(
  fabric: FabricModule,
  canvas: Canvas,
  visualImageUrl: string,
  used: Set<string>,
): Promise<void> {
  const image = await fabric.FabricImage.fromURL(
    visualImageUrl,
    { crossOrigin: "anonymous" },
    {
      id: "campaign-visual",
      name: "Campaign visual",
      role: "campaign-visual",
      imageFitMode: "fit",
      assetKey: assetKeyForSource(visualImageUrl),
      cropX: 0,
      cropY: 0,
    } as ConstructorParameters<typeof fabric.FabricImage>[1],
  );
  if (!image.width || !image.height) {
    throw new Error("The generated campaign visual has invalid dimensions.");
  }
  applyImageFit(image, canvas, "fit");
  const editorImage = image as FabricImage & EditorObject;
  editorImage.role = "campaign-visual";
  editorImage.imageFitMode = "fit";
  editorImage.assetKey = assetKeyForSource(visualImageUrl);
  editorImage.name = "Campaign visual";
  ensureObjectIdentity(image, 0, used, "campaign-visual");
  canvas.add(image);
}

export function dataUrlToBlob(dataUrl: string): Blob {
  const [metadata, encoded] = dataUrl.split(",", 2);
  if (!metadata || !encoded) throw new Error("Invalid canvas data URL.");
  const mime = metadata.match(/^data:([^;]+)/)?.[1] || "application/octet-stream";
  const bytes = metadata.includes(";base64")
    ? atob(encoded)
    : decodeURIComponent(encoded);
  const output = new Uint8Array(bytes.length);
  for (let index = 0; index < bytes.length; index += 1) output[index] = bytes.charCodeAt(index);
  return new Blob([output], { type: mime });
}

export function dataUrlBase64(dataUrl: string): string {
  const encoded = dataUrl.split(",", 2)[1];
  if (!encoded) throw new Error("Invalid canvas data URL.");
  return encoded;
}

export function resetViewport(canvas: Canvas): void {
  canvas.setViewportTransform([1, 0, 0, 1, 0, 0] as TMat2D);
  canvas.requestRenderAll();
}
