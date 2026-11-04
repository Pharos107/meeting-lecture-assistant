export type Word = {
  text: string;
  startMs: number;
  endMs: number;
};

export type SegmentMark = {
  startMs: number;
  endMs: number;
  quote: string;
};

export type Segment = {
  id: string;
  speakerLabel: string;
  startMs: number;
  endMs: number;
  textRaw: string;
  textEdited: string | null;
  words: Word[];
  marks: SegmentMark[];
};

export type Speaker = {
  label: string;
  name: string;
  source: "manual" | "voice_profile" | null;
};

export type ExportFormat = "md" | "docx" | "pdf" | "srt" | "vtt";

export type LiveLine = {
  id: string;
  text: string;
  stable: boolean;
  startMs?: number;
  /** Câu đã có trước khi mở trang: hiện ngay, không chạy chữ. */
  instant?: boolean;
};
