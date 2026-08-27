import type { Canvas, FabricObject } from "fabric";
import type {
  DesignResponse,
  EditorChannel,
  ImageFitMode,
  LayerType,
  SaveDesignPayload,
} from "@/lib/types";

export type {
  CanonicalLayer,
  DesignResponse,
  EditorChannel,
  ImageFitMode,
  JsonValue,
  LayerAppearance,
  LayerDocument,
  LayerTransform,
  LayerType,
  SaveDesignPayload,
} from "@/lib/types";

export const SUPPORTED_LAYER_TYPES = [
  "text",
  "image",
  "rect",
  "ellipse",
  "path",
  "group",
] as const satisfies readonly LayerType[];

export type CampaignEditorProps = {
  channel: EditorChannel;
  bootstrap: DesignResponse;
  visualImageUrl?: string;
  onSave: (payload: SaveDesignPayload) => Promise<DesignResponse>;
  onSaved?: (response: DesignResponse) => void;
  onClose?: () => void;
  onPngChange?: (blob: Blob) => void;
};

export type EditorLayerItem = {
  id: string;
  name: string;
  type: LayerType;
  visible: boolean;
  locked: boolean;
  object: FabricObject;
};

export type EditorToolbarProps = {
  canvas: Canvas | null;
  disabled: boolean;
  saving: boolean;
  dirty: boolean;
  canUndo: boolean;
  canRedo: boolean;
  selectionType: string | null;
  selectionFill: string;
  selectionFontFamily: string;
  selectionFontSize: number;
  selectionImageFitMode: ImageFitMode | null;
  canResetImage: boolean;
  replacingImage: boolean;
  backgroundColor: string;
  onAddText: () => void;
  onDelete: () => void;
  onTextFill: (value: string) => void;
  onBackground: (value: string) => void;
  onFontFamily: (value: string) => void;
  onFontSize: (value: number) => void;
  onBringForward: () => void;
  onSendBackward: () => void;
  onUndo: () => void;
  onRedo: () => void;
  onFit: () => void;
  onImageFitMode: (mode: ImageFitMode) => void;
  onReplaceImage: (file: File) => void;
  onResetImage: () => void;
  onSave: () => void;
  onDownload: (format: "svg" | "png" | "json") => void;
};
