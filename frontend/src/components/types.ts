export type Word = {
  text: string;
  startMs: number;
  endMs: number;
};

export type Segment = {
  id: string;
  speakerLabel: string;
  startMs: number;
  endMs: number;
  textRaw: string;
  textEdited: string | null;
  words: Word[];
  marked: boolean;
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
};
