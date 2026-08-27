"use client";

import { useEffect, useState } from "react";

import type { EditorLayerItem } from "./editor-types";

type LayersPanelProps = {
  layers: EditorLayerItem[];
  selectedId: string | null;
  disabled: boolean;
  onSelect: (layer: EditorLayerItem) => void;
  onVisibility: (layer: EditorLayerItem) => void;
  onLock: (layer: EditorLayerItem) => void;
  onRename: (layer: EditorLayerItem, name: string) => void;
  onForward: (layer: EditorLayerItem) => void;
  onBackward: (layer: EditorLayerItem) => void;
};

export default function LayersPanel({
  layers,
  selectedId,
  disabled,
  onSelect,
  onVisibility,
  onLock,
  onRename,
  onForward,
  onBackward,
}: LayersPanelProps) {
  const reversed = [...layers].reverse();

  return (
    <aside className="editor-layers" aria-label="Design layers">
      <div className="editor-panel-heading">
        <div>
          <span>Document</span>
          <h2>Layers</h2>
        </div>
        <strong>{layers.length}</strong>
      </div>
      {layers.length === 0 ? (
        <p className="editor-empty-layers">This design has no layers.</p>
      ) : (
        <ol className="editor-layer-list">
          {reversed.map((layer, visualIndex) => {
            const selected = selectedId === layer.id;
            const atTop = visualIndex === 0;
            const atBottom = visualIndex === reversed.length - 1;
            return (
              <li key={layer.id} className={selected ? "selected" : undefined}>
                <button
                  type="button"
                  className="editor-layer-main"
                  onClick={() => onSelect(layer)}
                  disabled={disabled}
                  aria-pressed={selected}
                  aria-label={`Select ${layer.name}`}
                  title={`Select ${layer.name}`}
                >
                  <span className="editor-layer-icon" aria-hidden="true">
                    {layer.type.slice(0, 1).toUpperCase()}
                  </span>
                  <span>
                    <small>{layer.type} layer · select</small>
                  </span>
                </button>
                <LayerNameInput
                  layer={layer}
                  disabled={disabled}
                  onRename={onRename}
                />
                <div className="editor-layer-actions">
                  <button
                    type="button"
                    onClick={() => onVisibility(layer)}
                    disabled={disabled}
                    aria-label={`${layer.visible ? "Hide" : "Show"} ${layer.name}`}
                    aria-pressed={layer.visible}
                  >
                    {layer.visible ? "Hide" : "Show"}
                  </button>
                  <button
                    type="button"
                    onClick={() => onLock(layer)}
                    disabled={disabled}
                    aria-label={`${layer.locked ? "Unlock" : "Lock"} ${layer.name}`}
                    aria-pressed={layer.locked}
                  >
                    {layer.locked ? "Unlock" : "Lock"}
                  </button>
                  <button
                    type="button"
                    onClick={() => onForward(layer)}
                    disabled={disabled || atTop}
                    aria-label={`Bring ${layer.name} forward`}
                  >
                    ↑
                  </button>
                  <button
                    type="button"
                    onClick={() => onBackward(layer)}
                    disabled={disabled || atBottom}
                    aria-label={`Send ${layer.name} backward`}
                  >
                    ↓
                  </button>
                </div>
              </li>
            );
          })}
        </ol>
      )}
    </aside>
  );
}

function LayerNameInput({
  layer,
  disabled,
  onRename,
}: {
  layer: EditorLayerItem;
  disabled: boolean;
  onRename: (layer: EditorLayerItem, name: string) => void;
}) {
  const [value, setValue] = useState(layer.name);

  useEffect(() => {
    setValue(layer.name);
  }, [layer.name]);

  function commit() {
    const next = value.trim().slice(0, 80);
    if (!next) {
      setValue(layer.name);
      return;
    }
    setValue(next);
    onRename(layer, next);
  }

  return (
    <label className="editor-layer-rename">
      <span className="sr-only">Rename {layer.name}</span>
      <input
        type="text"
        value={value}
        maxLength={80}
        disabled={disabled}
        aria-label={`Layer name: ${layer.name}`}
        onChange={(event) => setValue(event.target.value)}
        onBlur={commit}
        onKeyDown={(event) => {
          if (event.key === "Enter") {
            event.preventDefault();
            event.currentTarget.blur();
          } else if (event.key === "Escape") {
            setValue(layer.name);
            event.currentTarget.blur();
          }
        }}
      />
    </label>
  );
}
