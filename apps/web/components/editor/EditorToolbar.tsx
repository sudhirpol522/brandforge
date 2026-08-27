"use client";

import { useRef } from "react";

import type { EditorToolbarProps } from "./editor-types";

const FONTS = ["Arial", "Helvetica", "Georgia", "Times New Roman", "Courier New", "Verdana"];

export default function EditorToolbar({
  canvas,
  disabled,
  saving,
  dirty,
  canUndo,
  canRedo,
  selectionType,
  selectionFill,
  selectionFontFamily,
  selectionFontSize,
  selectionImageFitMode,
  canResetImage,
  replacingImage,
  backgroundColor,
  onAddText,
  onDelete,
  onTextFill,
  onBackground,
  onFontFamily,
  onFontSize,
  onBringForward,
  onSendBackward,
  onUndo,
  onRedo,
  onFit,
  onImageFitMode,
  onReplaceImage,
  onResetImage,
  onSave,
  onDownload,
}: EditorToolbarProps) {
  const imageInputRef = useRef<HTMLInputElement>(null);
  const hasSelection = Boolean(canvas?.getActiveObject());
  const isText = selectionType === "text";
  const isImage = selectionType === "image";

  return (
    <>
      <div className="editor-toolbar" role="toolbar" aria-label="Design editing tools">
      <div className="editor-tool-group">
        <button type="button" onClick={onAddText} disabled={disabled} aria-label="Add text layer">
          + Text
        </button>
        <button
          type="button"
          onClick={onDelete}
          disabled={disabled || !hasSelection}
          aria-label="Delete selected layer"
        >
          Delete
        </button>
      </div>

      <div className="editor-tool-group editor-color-tools">
        <label>
          <span>Fill</span>
          <input
            type="color"
            value={selectionFill}
            onChange={(event) => onTextFill(event.target.value)}
            disabled={disabled || !hasSelection}
            aria-label="Selected layer fill color"
          />
        </label>
        <label>
          <span>Canvas</span>
          <input
            type="color"
            value={backgroundColor}
            onChange={(event) => onBackground(event.target.value)}
            disabled={disabled}
            aria-label="Canvas background color"
          />
        </label>
      </div>

      <div className="editor-tool-group editor-text-tools" aria-label="Text formatting">
        <label>
          <span className="sr-only">Font family</span>
          <select
            value={selectionFontFamily}
            onChange={(event) => onFontFamily(event.target.value)}
            disabled={disabled || !isText}
            aria-label="Font family"
          >
            {FONTS.map((font) => (
              <option key={font} value={font}>{font}</option>
            ))}
          </select>
        </label>
        <label>
          <span className="sr-only">Font size</span>
          <input
            type="number"
            min={6}
            max={400}
            value={selectionFontSize}
            onChange={(event) => onFontSize(Number(event.target.value))}
            disabled={disabled || !isText}
            aria-label="Font size"
          />
        </label>
      </div>

      <div className="editor-tool-group">
        <button type="button" onClick={onBringForward} disabled={disabled || !hasSelection}>
          Forward
        </button>
        <button type="button" onClick={onSendBackward} disabled={disabled || !hasSelection}>
          Backward
        </button>
        <button type="button" onClick={onUndo} disabled={disabled || !canUndo} aria-label="Undo">
          Undo
        </button>
        <button type="button" onClick={onRedo} disabled={disabled || !canRedo} aria-label="Redo">
          Redo
        </button>
        <button type="button" onClick={onFit} disabled={disabled} aria-label="Fit design to view">
          Fit view
        </button>
      </div>

      <div className="editor-tool-group editor-export-tools">
        <button type="button" onClick={() => onDownload("svg")} disabled={disabled}>SVG</button>
        <button type="button" onClick={() => onDownload("png")} disabled={disabled}>PNG</button>
        <button type="button" onClick={() => onDownload("json")} disabled={disabled}>JSON</button>
        <button
          type="button"
          className="editor-save-button"
          onClick={onSave}
          disabled={disabled || saving || !dirty}
        >
          {saving ? "Saving…" : dirty ? "Save draft" : "Saved"}
        </button>
      </div>
      </div>

      {isImage && (
        <div className="editor-image-toolbar" role="toolbar" aria-label="Selected image tools">
          <strong>Image</strong>
          {(["fit", "fill", "crop"] as const).map((mode) => (
            <button
              type="button"
              key={mode}
              onClick={() => onImageFitMode(mode)}
              disabled={disabled || replacingImage}
              aria-pressed={selectionImageFitMode === mode}
              title={
                mode === "crop"
                  ? "Fill the canvas and reposition the image to adjust the crop"
                  : `${mode[0].toUpperCase()}${mode.slice(1)} image to canvas`
              }
            >
              {mode[0].toUpperCase() + mode.slice(1)}
            </button>
          ))}
          <input
            ref={imageInputRef}
            className="sr-only"
            type="file"
            accept="image/*"
            aria-label="Choose replacement image"
            onChange={(event) => {
              const file = event.target.files?.[0];
              if (file) onReplaceImage(file);
              event.target.value = "";
            }}
          />
          <button
            type="button"
            onClick={() => imageInputRef.current?.click()}
            disabled={disabled || replacingImage}
          >
            {replacingImage ? "Replacing…" : "Replace"}
          </button>
          <button
            type="button"
            onClick={onResetImage}
            disabled={disabled || replacingImage || !canResetImage}
            title={canResetImage ? "Reset campaign visual to its default fit" : "Reset is available for the campaign visual"}
          >
            Reset
          </button>
          {selectionImageFitMode === "crop" && (
            <span className="editor-image-hint">Drag the image to reposition its crop.</span>
          )}
        </div>
      )}
    </>
  );
}
