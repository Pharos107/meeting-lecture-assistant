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
  textCleaned: string | null;
  textEdited: string | null;
  words: Word[];
  marked: boolean;
};

export type Speaker = {
  label: string;
  name: string;
  source: "manual" | "voice_profile" | null;
};

export type TranscriptMode = "raw" | "cleaned";

export type ExportFormat = "md" | "docx" | "pdf" | "srt" | "vtt";

export type MinutesTemplate = "meeting" | "lecture";

export type LiveLine = {
  id: string;
  text: string;
  stable: boolean;
};
