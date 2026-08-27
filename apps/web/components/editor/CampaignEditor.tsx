"use client";

import {
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import type { Canvas, FabricImage, FabricObject } from "fabric";

import EditorToolbar from "./EditorToolbar";
import LayersPanel from "./LayersPanel";
import {
  applyImageFit,
  assetKeyForSource,
  dataUrlBase64,
  dataUrlToBlob,
  ensureObjectIdentity,
  loadBootstrapDesign,
  objectLayerType,
  parseSvgDimensions,
  resetViewport,
  serializeLayerDocument,
  type EditorObject,
} from "./fabric-utils";
import type {
  CampaignEditorProps,
  EditorLayerItem,
  ImageFitMode,
  SaveDesignPayload,
} from "./editor-types";

type TextObject = FabricObject & {
  fontFamily?: string;
  fontSize?: number;
  text?: string;
  enterEditing?: () => void;
  selectAll?: () => void;
  editable?: boolean;
};

const HISTORY_LIMIT = 50;
const MAX_REPLACEMENT_BYTES = 10 * 1024 * 1024;
const CUSTOM_PROPERTIES = [
  "id",
  "name",
  "role",
  "imageFitMode",
  "assetKey",
  "brandLocked",
];

function hexColor(value: unknown, fallback = "#101a35"): string {
  return typeof value === "string" && /^#[0-9a-f]{6}$/i.test(value) ? value : fallback;
}

function downloadFile(contents: BlobPart, type: string, filename: string): void {
  const url = URL.createObjectURL(new Blob([contents], { type }));
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

function fileToDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.onerror = () => reject(new Error("The replacement image could not be read."));
    reader.readAsDataURL(file);
  });
}

function textOverflowWarnings(editorCanvas: Canvas): string[] {
  const marginX = editorCanvas.getWidth() * 0.05;
  const marginY = editorCanvas.getHeight() * 0.05;
  const safeRight = editorCanvas.getWidth() - marginX;
  const safeBottom = editorCanvas.getHeight() - marginY;
  return editorCanvas.getObjects().flatMap((object, index) => {
    if (objectLayerType(object) !== "text" || (object as TextObject).editable === false) return [];
    const bounds = object.getBoundingRect();
    const outside =
      bounds.left < marginX ||
      bounds.top < marginY ||
      bounds.left + bounds.width > safeRight ||
      bounds.top + bounds.height > safeBottom;
    if (!outside) return [];
    const editorObject = object as EditorObject;
    return [editorObject.name || `Text ${index + 1}`];
  });
}

export default function CampaignEditor({
  channel,
  bootstrap,
  visualImageUrl,
  onSave,
  onSaved,
  onClose,
  onPngChange,
}: CampaignEditorProps) {
  const canvasElementRef = useRef<HTMLCanvasElement>(null);
  const stageRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<Canvas | null>(null);
  const fabricRef = useRef<typeof import("fabric") | null>(null);
  const restoringRef = useRef(false);
  const initializedRef = useRef(false);
  const historyRef = useRef<string[]>([]);
  const historyIndexRef = useRef(-1);
  const savedHistoryIndexRef = useRef(0);
  const revisionRef = useRef(bootstrap.revision);
  const dimensionsRef = useRef({
    width: bootstrap.layer_document.width,
    height: bootstrap.layer_document.height,
  });
  const pngCallbackRef = useRef(onPngChange);
  const pngTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const [canvas, setCanvas] = useState<Canvas | null>(null);
  const [layers, setLayers] = useState<EditorLayerItem[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selectionType, setSelectionType] = useState<string | null>(null);
  const [selectionFill, setSelectionFill] = useState("#101a35");
  const [selectionFontFamily, setSelectionFontFamily] = useState("Arial");
  const [selectionFontSize, setSelectionFontSize] = useState(40);
  const [selectionImageFitMode, setSelectionImageFitMode] =
    useState<ImageFitMode | null>(null);
  const [canResetImage, setCanResetImage] = useState(false);
  const [backgroundColor, setBackgroundColor] = useState("#ffffff");
  const [displaySize, setDisplaySize] = useState(dimensionsRef.current);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [replacingImage, setReplacingImage] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [canUndo, setCanUndo] = useState(false);
  const [canRedo, setCanRedo] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [overflowLayers, setOverflowLayers] = useState<string[]>([]);

  useEffect(() => {
    pngCallbackRef.current = onPngChange;
  }, [onPngChange]);

  const syncHistoryButtons = useCallback(() => {
    setCanUndo(historyIndexRef.current > 0);
    setCanRedo(historyIndexRef.current < historyRef.current.length - 1);
  }, []);

  const syncSelection = useCallback((editorCanvas: Canvas) => {
    const active = editorCanvas.getActiveObject() as TextObject | undefined;
    const type = active && active.type.toLowerCase() !== "activeselection"
      ? objectLayerType(active)
      : null;
    const editorObject = active as EditorObject | undefined;
    setSelectedId((active as EditorObject | undefined)?.id ?? null);
    setSelectionType(type);
    setSelectionFill(hexColor(active?.fill));
    setSelectionImageFitMode(type === "image" ? editorObject?.imageFitMode || "fit" : null);
    setCanResetImage(
      type === "image" &&
      (editorObject?.role === "campaign-visual" || editorObject?.id === "campaign-visual"),
    );
    if (type === "text") {
      setSelectionFontFamily(active?.fontFamily || "Arial");
      setSelectionFontSize(active?.fontSize || 40);
    }
  }, []);

  const syncOverflow = useCallback((editorCanvas: Canvas) => {
    setOverflowLayers(textOverflowWarnings(editorCanvas));
  }, []);

  const syncLayers = useCallback((editorCanvas: Canvas) => {
    try {
      const used = new Set<string>();
      const next = editorCanvas.getObjects().map((object, index) => {
        const identified = ensureObjectIdentity(object, index, used);
        return {
          id: identified.id!,
          name: identified.name!,
          type: objectLayerType(object),
          visible: object.visible,
          locked: !object.selectable || !object.evented,
          object,
        };
      });
      setLayers(next);
      setBackgroundColor(hexColor(editorCanvas.backgroundColor, "#ffffff"));
      syncSelection(editorCanvas);
      syncOverflow(editorCanvas);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Unable to read the design layers.");
    }
  }, [syncOverflow, syncSelection]);

  const emitPng = useCallback((editorCanvas: Canvas) => {
    if (!pngCallbackRef.current) return;
    if (pngTimerRef.current) clearTimeout(pngTimerRef.current);
    pngTimerRef.current = setTimeout(() => {
      try {
        const dataUrl = editorCanvas.toDataURL({ format: "png", multiplier: 2 });
        pngCallbackRef.current?.(dataUrlToBlob(dataUrl));
      } catch (cause) {
        setError(cause instanceof Error ? cause.message : "Unable to create the PNG preview.");
      }
    }, 180);
  }, []);

  const pushHistory = useCallback((editorCanvas: Canvas, markDirty = true) => {
    if (restoringRef.current || !initializedRef.current) return;
    const snapshot = JSON.stringify(editorCanvas.toJSON());
    if (historyRef.current[historyIndexRef.current] === snapshot) return;
    historyRef.current = historyRef.current.slice(0, historyIndexRef.current + 1);
    historyRef.current.push(snapshot);
    if (historyRef.current.length > HISTORY_LIMIT) {
      historyRef.current.shift();
      savedHistoryIndexRef.current -= 1;
    }
    historyIndexRef.current = historyRef.current.length - 1;
    if (markDirty) setDirty(true);
    syncHistoryButtons();
    syncLayers(editorCanvas);
    emitPng(editorCanvas);
  }, [emitPng, syncHistoryButtons, syncLayers]);

  const fitView = useCallback(() => {
    const stage = stageRef.current;
    const editorCanvas = canvasRef.current;
    if (!stage || !editorCanvas) return;
    resetViewport(editorCanvas);
    const { width, height } = dimensionsRef.current;
    const availableWidth = Math.max(240, stage.clientWidth - 48);
    const availableHeight = Math.max(240, stage.clientHeight - 48);
    const ratio = Math.min(1, availableWidth / width, availableHeight / height);
    setDisplaySize({ width: Math.round(width * ratio), height: Math.round(height * ratio) });
  }, []);

  useEffect(() => {
    let cancelled = false;
    let editorCanvas: Canvas | null = null;

    async function initialize() {
      try {
        setLoading(true);
        setError(null);
        const fabric = await import("fabric");
        if (cancelled || !canvasElementRef.current) return;
        fabricRef.current = fabric;
        fabric.FabricObject.customProperties = CUSTOM_PROPERTIES;
        const hasCache = Object.keys(bootstrap.fabric_json).length > 0;
        const dimensions = hasCache
          ? { width: bootstrap.layer_document.width, height: bootstrap.layer_document.height }
          : parseSvgDimensions(
              bootstrap.svg,
              bootstrap.layer_document.width,
              bootstrap.layer_document.height,
            );
        dimensionsRef.current = dimensions;
        editorCanvas = new fabric.Canvas(canvasElementRef.current, {
          width: dimensions.width,
          height: dimensions.height,
          backgroundColor: "#ffffff",
          preserveObjectStacking: true,
          selection: true,
        });
        canvasRef.current = editorCanvas;
        setCanvas(editorCanvas);

        restoringRef.current = true;
        await loadBootstrapDesign(fabric, editorCanvas, bootstrap, visualImageUrl);
        serializeLayerDocument(
          editorCanvas,
          channel,
          dimensions.width,
          dimensions.height,
        );
        editorCanvas.requestRenderAll();
        restoringRef.current = false;
        initializedRef.current = true;

        const firstSnapshot = JSON.stringify(editorCanvas.toJSON());
        historyRef.current = [firstSnapshot];
        historyIndexRef.current = 0;
        savedHistoryIndexRef.current = 0;
        syncHistoryButtons();
        syncLayers(editorCanvas);
        emitPng(editorCanvas);

        const onChanged = () => pushHistory(editorCanvas!);
        const onSelection = () => syncSelection(editorCanvas!);
        const onLiveTransform = () => syncOverflow(editorCanvas!);
        editorCanvas.on("object:added", onChanged);
        editorCanvas.on("object:removed", onChanged);
        editorCanvas.on("object:modified", onChanged);
        editorCanvas.on("object:moving", onLiveTransform);
        editorCanvas.on("object:scaling", onLiveTransform);
        editorCanvas.on("text:changed", onChanged);
        editorCanvas.on("selection:created", onSelection);
        editorCanvas.on("selection:updated", onSelection);
        editorCanvas.on("selection:cleared", onSelection);
        setLoading(false);
        requestAnimationFrame(fitView);
      } catch (cause) {
        restoringRef.current = false;
        setError(cause instanceof Error ? cause.message : "Unable to initialize the editor.");
        setLoading(false);
      }
    }

    void initialize();
    return () => {
      cancelled = true;
      initializedRef.current = false;
      if (pngTimerRef.current) clearTimeout(pngTimerRef.current);
      canvasRef.current = null;
      setCanvas(null);
      if (editorCanvas) void editorCanvas.dispose();
    };
  }, [
    bootstrap,
    channel,
    emitPng,
    fitView,
    pushHistory,
    syncHistoryButtons,
    syncLayers,
    syncOverflow,
    syncSelection,
    visualImageUrl,
  ]);

  useEffect(() => {
    const stage = stageRef.current;
    if (!stage) return;
    const observer = new ResizeObserver(() => fitView());
    observer.observe(stage);
    return () => observer.disconnect();
  }, [fitView]);

  const mutateSelection = useCallback((values: Record<string, unknown>) => {
    const editorCanvas = canvasRef.current;
    const active = editorCanvas?.getActiveObject();
    if (!editorCanvas || !active) return;
    active.set(values);
    active.setCoords();
    editorCanvas.requestRenderAll();
    pushHistory(editorCanvas);
  }, [pushHistory]);

  const addText = useCallback(() => {
    const editorCanvas = canvasRef.current;
    const fabric = fabricRef.current;
    if (!editorCanvas || !fabric) return;
    const { width, height } = dimensionsRef.current;
    const object = new fabric.Textbox("Edit this text", {
      left: width * 0.2,
      top: height * 0.2,
      width: width * 0.6,
      fill: "#101a35",
      fontFamily: "Arial",
      fontSize: Math.max(24, Math.round(width / 18)),
      editable: true,
    }) as TextObject;
    ensureObjectIdentity(object, editorCanvas.getObjects().length);
    editorCanvas.add(object);
    editorCanvas.setActiveObject(object);
    editorCanvas.requestRenderAll();
    object.enterEditing?.();
    object.selectAll?.();
    syncLayers(editorCanvas);
  }, [syncLayers]);

  const deleteSelection = useCallback(() => {
    const editorCanvas = canvasRef.current;
    const active = editorCanvas?.getActiveObject() as
      | (FabricObject & { getObjects?: () => FabricObject[] })
      | undefined;
    if (!editorCanvas || !active) return;
    const objects = active.type.toLowerCase() === "activeselection" && active.getObjects
      ? active.getObjects()
      : [active];
    editorCanvas.discardActiveObject();
    editorCanvas.remove(...objects);
    editorCanvas.requestRenderAll();
  }, []);

  const moveSelection = useCallback((forward: boolean, object?: FabricObject) => {
    const editorCanvas = canvasRef.current;
    const target = object || editorCanvas?.getActiveObject();
    if (!editorCanvas || !target) return;
    if (forward) editorCanvas.bringObjectForward(target);
    else editorCanvas.sendObjectBackwards(target);
    editorCanvas.requestRenderAll();
    pushHistory(editorCanvas);
  }, [pushHistory]);

  const applySelectedImageMode = useCallback((mode: ImageFitMode) => {
    const editorCanvas = canvasRef.current;
    const active = editorCanvas?.getActiveObject();
    if (!editorCanvas || !active || objectLayerType(active) !== "image") return;
    try {
      applyImageFit(active as FabricImage, editorCanvas, mode);
      setSelectionImageFitMode(mode);
      editorCanvas.requestRenderAll();
      pushHistory(editorCanvas);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Unable to resize the selected image.");
    }
  }, [pushHistory]);

  const resetSelectedImage = useCallback(() => {
    const editorCanvas = canvasRef.current;
    const active = editorCanvas?.getActiveObject();
    if (!editorCanvas || !active || objectLayerType(active) !== "image") return;
    const editorObject = active as EditorObject;
    if (editorObject.role !== "campaign-visual" && editorObject.id !== "campaign-visual") return;
    applyImageFit(active as FabricImage, editorCanvas, "fit");
    setSelectionImageFitMode("fit");
    editorCanvas.requestRenderAll();
    pushHistory(editorCanvas);
  }, [pushHistory]);

  const replaceSelectedImage = useCallback(async (file: File) => {
    const editorCanvas = canvasRef.current;
    const fabric = fabricRef.current;
    const active = editorCanvas?.getActiveObject();
    if (!editorCanvas || !fabric || !active || objectLayerType(active) !== "image") return;
    if (!file.type.toLowerCase().startsWith("image/")) {
      setError("Choose a valid image file.");
      return;
    }
    if (file.size > MAX_REPLACEMENT_BYTES) {
      setError("Replacement images must be 10 MiB or smaller.");
      return;
    }
    if (!file.size) {
      setError("The replacement image is empty.");
      return;
    }

    const previous = active as FabricImage & EditorObject;
    const stackIndex = editorCanvas.getObjects().indexOf(active);
    if (stackIndex < 0) return;
    try {
      setReplacingImage(true);
      setError(null);
      const dataUrl = await fileToDataUrl(file);
      const replacement = await fabric.FabricImage.fromURL(dataUrl);
      if (!replacement.width || !replacement.height) {
        throw new Error("The replacement image has invalid dimensions.");
      }
      const replacementObject = replacement as FabricImage & EditorObject;
      replacementObject.id = previous.id;
      replacementObject.name = previous.name || "Image";
      replacementObject.role = previous.role;
      replacementObject.brandLocked = previous.brandLocked;
      replacementObject.assetKey = assetKeyForSource(
        `${file.name}:${file.size}:${file.lastModified}`,
      );
      replacement.set({
        visible: previous.visible,
        opacity: previous.opacity,
        selectable: previous.selectable,
        evented: previous.evented,
        lockMovementX: previous.lockMovementX,
        lockMovementY: previous.lockMovementY,
        lockRotation: previous.lockRotation,
        lockScalingX: previous.lockScalingX,
        lockScalingY: previous.lockScalingY,
      });
      applyImageFit(replacement, editorCanvas, "fit");

      restoringRef.current = true;
      editorCanvas.discardActiveObject();
      editorCanvas.remove(previous);
      editorCanvas.insertAt(stackIndex, replacement);
      restoringRef.current = false;
      editorCanvas.setActiveObject(replacement);
      editorCanvas.requestRenderAll();
      setSelectionImageFitMode("fit");
      pushHistory(editorCanvas);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Unable to replace the selected image.");
    } finally {
      restoringRef.current = false;
      setReplacingImage(false);
    }
  }, [pushHistory]);

  const restoreHistory = useCallback(async (index: number) => {
    const editorCanvas = canvasRef.current;
    const snapshot = historyRef.current[index];
    if (!editorCanvas || !snapshot || index < 0 || index >= historyRef.current.length) return;
    try {
      restoringRef.current = true;
      editorCanvas.discardActiveObject();
      await editorCanvas.loadFromJSON(snapshot);
      historyIndexRef.current = index;
      editorCanvas.requestRenderAll();
      syncHistoryButtons();
      syncLayers(editorCanvas);
      setDirty(index !== savedHistoryIndexRef.current);
      emitPng(editorCanvas);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Unable to restore editor history.");
    } finally {
      restoringRef.current = false;
    }
  }, [emitPng, syncHistoryButtons, syncLayers]);

  const toggleVisibility = useCallback((layer: EditorLayerItem) => {
    const editorCanvas = canvasRef.current;
    if (!editorCanvas) return;
    layer.object.set("visible", !layer.object.visible);
    if (!layer.object.visible) editorCanvas.discardActiveObject();
    editorCanvas.requestRenderAll();
    pushHistory(editorCanvas);
  }, [pushHistory]);

  const toggleLock = useCallback((layer: EditorLayerItem) => {
    const editorCanvas = canvasRef.current;
    if (!editorCanvas) return;
    const locked = layer.object.selectable && layer.object.evented;
    layer.object.set({
      selectable: !locked,
      evented: !locked,
      lockMovementX: locked,
      lockMovementY: locked,
      lockRotation: locked,
      lockScalingX: locked,
      lockScalingY: locked,
    });
    if (locked) editorCanvas.discardActiveObject();
    editorCanvas.requestRenderAll();
    pushHistory(editorCanvas);
  }, [pushHistory]);

  const renameLayer = useCallback((layer: EditorLayerItem, nextName: string) => {
    const editorCanvas = canvasRef.current;
    const name = nextName.trim().slice(0, 80);
    if (!editorCanvas || !name || name === layer.name) return;
    (layer.object as EditorObject).name = name;
    editorCanvas.requestRenderAll();
    pushHistory(editorCanvas);
  }, [pushHistory]);

  const selectLayer = useCallback((layer: EditorLayerItem) => {
    const editorCanvas = canvasRef.current;
    if (!editorCanvas || !layer.object.visible || !layer.object.selectable) return;
    editorCanvas.setActiveObject(layer.object);
    editorCanvas.requestRenderAll();
    syncSelection(editorCanvas);
    stageRef.current?.focus();
  }, [syncSelection]);

  const changeBackground = useCallback((value: string) => {
    const editorCanvas = canvasRef.current;
    if (!editorCanvas) return;
    editorCanvas.set("backgroundColor", value);
    editorCanvas.requestRenderAll();
    setBackgroundColor(value);
    pushHistory(editorCanvas);
  }, [pushHistory]);

  const saveDraft = useCallback(async () => {
    const editorCanvas = canvasRef.current;
    if (!editorCanvas || saving) return;
    try {
      setSaving(true);
      setError(null);
      setNotice(null);
      editorCanvas.discardActiveObject();
      editorCanvas.requestRenderAll();
      const { width, height } = dimensionsRef.current;
      const preview = editorCanvas.toDataURL({ format: "png", multiplier: 2 });
      const response = await onSave({
        channel,
        layer_document: serializeLayerDocument(editorCanvas, channel, width, height),
        fabric_json: editorCanvas.toJSON() as SaveDesignPayload["fabric_json"],
        svg: editorCanvas.toSVG({
          suppressPreamble: true,
          width: `${width}`,
          height: `${height}`,
        }),
        preview_png_base64: dataUrlBase64(preview),
        expected_revision: revisionRef.current,
        editor_version: "7",
      });
      revisionRef.current = response.revision;
      savedHistoryIndexRef.current = historyIndexRef.current;
      setDirty(false);
      setNotice(`Draft revision ${response.revision} saved.`);
      pngCallbackRef.current?.(dataUrlToBlob(preview));
      onSaved?.(response);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Unable to save this draft.");
    } finally {
      setSaving(false);
    }
  }, [channel, onSave, onSaved, saving]);

  const download = useCallback((format: "svg" | "png" | "json") => {
    const editorCanvas = canvasRef.current;
    if (!editorCanvas) return;
    try {
      const { width, height } = dimensionsRef.current;
      const base = `brandforge-${channel}-r${revisionRef.current}`;
      if (format === "svg") {
        downloadFile(
          editorCanvas.toSVG({
            suppressPreamble: true,
            width: `${width}`,
            height: `${height}`,
          }),
          "image/svg+xml",
          `${base}.svg`,
        );
      } else if (format === "png") {
        const blob = dataUrlToBlob(editorCanvas.toDataURL({ format: "png", multiplier: 2 }));
        downloadFile(blob, "image/png", `${base}@2x.png`);
      } else {
        const document = serializeLayerDocument(editorCanvas, channel, width, height);
        downloadFile(JSON.stringify(document, null, 2), "application/json", `${base}.json`);
      }
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : `Unable to download ${format.toUpperCase()}.`);
    }
  }, [channel]);

  const close = useCallback(() => {
    if (!onClose) return;
    if (!dirty || window.confirm("Close the editor and discard unsaved changes?")) onClose();
  }, [dirty, onClose]);

  const handleKeyDown = useCallback((event: React.KeyboardEvent<HTMLDivElement>) => {
    const target = event.target as HTMLElement;
    if (target.matches("input, select, textarea") || target.isContentEditable) return;
    if ((event.key === "Delete" || event.key === "Backspace") && canvasRef.current?.getActiveObject()) {
      event.preventDefault();
      deleteSelection();
    }
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "z") {
      event.preventDefault();
      void restoreHistory(historyIndexRef.current + (event.shiftKey ? 1 : -1));
    }
  }, [deleteSelection, restoreHistory]);

  const disabled = loading || Boolean(error && !canvas);

  return (
    <section
      className="campaign-editor"
      aria-label={`${channel} campaign editor`}
      aria-busy={loading || saving}
      onKeyDown={handleKeyDown}
    >
      <header className="editor-header">
        <div>
          <span className="editor-kicker">BrandForge studio</span>
          <h1>{channel} design</h1>
          <p>
            Revision {revisionRef.current}
            <span className={`editor-dirty-dot${dirty ? " active" : ""}`} aria-hidden="true" />
            {dirty ? "Unsaved changes" : "All changes saved"}
          </p>
        </div>
        {onClose && (
          <button type="button" className="editor-close" onClick={close} aria-label="Close editor">
            Close
          </button>
        )}
      </header>

      <EditorToolbar
        canvas={canvas}
        disabled={disabled}
        saving={saving}
        dirty={dirty}
        canUndo={canUndo}
        canRedo={canRedo}
        selectionType={selectionType}
        selectionFill={selectionFill}
        selectionFontFamily={selectionFontFamily}
        selectionFontSize={selectionFontSize}
        selectionImageFitMode={selectionImageFitMode}
        canResetImage={canResetImage}
        replacingImage={replacingImage}
        backgroundColor={backgroundColor}
        onAddText={addText}
        onDelete={deleteSelection}
        onTextFill={(value) => mutateSelection({ fill: value })}
        onBackground={changeBackground}
        onFontFamily={(value) => mutateSelection({ fontFamily: value })}
        onFontSize={(value) => mutateSelection({ fontSize: Math.min(400, Math.max(6, value)) })}
        onBringForward={() => moveSelection(true)}
        onSendBackward={() => moveSelection(false)}
        onUndo={() => void restoreHistory(historyIndexRef.current - 1)}
        onRedo={() => void restoreHistory(historyIndexRef.current + 1)}
        onFit={fitView}
        onImageFitMode={applySelectedImageMode}
        onReplaceImage={(file) => void replaceSelectedImage(file)}
        onResetImage={resetSelectedImage}
        onSave={() => void saveDraft()}
        onDownload={download}
      />

      {overflowLayers.length > 0 && (
        <div className="editor-overflow-warning" role="status">
          <strong>Text outside safe area</strong>
          <span>
            {overflowLayers.join(", ")} {overflowLayers.length === 1 ? "extends" : "extend"} beyond
            the 5% content boundary.
          </span>
        </div>
      )}

      {(error || notice) && (
        <div
          className={`editor-message ${error ? "error" : "success"}`}
          role={error ? "alert" : "status"}
        >
          <span>{error || notice}</span>
          <button
            type="button"
            onClick={() => error ? setError(null) : setNotice(null)}
            aria-label="Dismiss message"
          >
            ×
          </button>
        </div>
      )}

      <div className="editor-workspace">
        <div
          className="editor-stage"
          ref={stageRef}
          tabIndex={0}
          aria-label="Design canvas. Use Delete to remove a selected layer and Command Z to undo."
        >
          {loading && (
            <div className="editor-loading" role="status">
              <span />
              Preparing editable layers…
            </div>
          )}
          <div
            className="editor-canvas-frame"
            style={{ width: displaySize.width, height: displaySize.height }}
          >
            <canvas ref={canvasElementRef} aria-label={`${channel} editable design`} />
          </div>
        </div>

        <LayersPanel
          layers={layers}
          selectedId={selectedId}
          disabled={disabled}
          onSelect={selectLayer}
          onVisibility={toggleVisibility}
          onLock={toggleLock}
          onRename={renameLayer}
          onForward={(layer) => moveSelection(true, layer.object)}
          onBackward={(layer) => moveSelection(false, layer.object)}
        />
      </div>
    </section>
  );
}
