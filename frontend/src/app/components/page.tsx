"use client";

import { useEffect, useState, type ReactNode } from "react";
import { AiActionPanel } from "@/components/ai-action-panel";
import { AudioPlayerBar } from "@/components/audio-player-bar";
import { AudioUploader } from "@/components/audio-uploader";
import { LiveTranscript } from "@/components/live-transcript";
import { SelectionToolbar } from "@/components/selection-toolbar";
import { SpeakerList } from "@/components/speaker-list";
import { TranscriptLayout } from "@/components/transcript-layout";
import type { ExportFormat, LiveLine, MinutesTemplate, Segment, Speaker, TranscriptMode } from "@/components/types";

const DURATION_MS = 96_000;

const INITIAL_SPEAKERS: Speaker[] = [
  { label: "SPEAKER_00", name: "Lê Hải Đăng", source: "voice_profile" },
  { label: "SPEAKER_01", name: "SPEAKER_01", source: null },
];

function words(text: string, startMs: number, endMs: number) {
  const parts = text.split(" ");
  const step = (endMs - startMs) / parts.length;
  return parts.map((textPart, index) => ({
    text: textPart,
    startMs: Math.round(startMs + step * index),
    endMs: Math.round(startMs + step * (index + 1)),
  }));
}

const INITIAL_SEGMENTS: Segment[] = [
  {
    id: "seg-1",
    speakerLabel: "SPEAKER_00",
    startMs: 1_200,
    endMs: 18_400,
    textRaw: "Mình chốt phạm vi demo gồm tải file và nghe trực tiếp.",
    textCleaned: "Mình chốt phạm vi demo, gồm tải file và nghe trực tiếp.",
    textEdited: null,
    marked: false,
    words: words("Mình chốt phạm vi demo gồm tải file và nghe trực tiếp.", 1_200, 18_400),
  },
  {
    id: "seg-2",
    speakerLabel: "SPEAKER_01",
    startMs: 19_000,
    endMs: 41_000,
    textRaw: "Phần người nói chạy pyannote sau khi Whisper đã nhả GPU.",
    textCleaned: "Phần người nói chạy pyannote sau khi Whisper đã nhả GPU.",
    textEdited: null,
    marked: false,
    words: words("Phần người nói chạy pyannote sau khi Whisper đã nhả GPU.", 19_000, 41_000),
  },
  {
    id: "seg-3",
    speakerLabel: "SPEAKER_00",
    startMs: 42_500,
    endMs: 68_000,
    textRaw: "Bôi đen một đoạn trong câu để đánh dấu hoặc tạo việc tại mốc đó.",
    textCleaned: "Bôi đen một đoạn trong câu để đánh dấu, hoặc tạo việc tại mốc đó.",
    textEdited: "Bôi đen một đoạn trong câu để đánh dấu hoặc tạo việc cần làm.",
    marked: true,
    words: words("Bôi đen một đoạn trong câu để đánh dấu hoặc tạo việc tại mốc đó.", 42_500, 68_000),
  },
  {
    id: "seg-4",
    speakerLabel: "SPEAKER_01",
    startMs: 69_200,
    endMs: 92_000,
    textRaw: "Khi dừng nghe, bản chuẩn quét lại cả file rồi mới thay bản nháp.",
    textCleaned: "Khi dừng nghe, bản chuẩn quét lại cả file, rồi mới thay bản nháp.",
    textEdited: null,
    marked: false,
    words: words("Khi dừng nghe, bản chuẩn quét lại cả file rồi mới thay bản nháp.", 69_200, 92_000),
  },
];

const LIVE_LINES: LiveLine[] = [
  { id: "l1", stable: true, text: "Hôm nay mình xem lại luồng tải file và luồng nghe trực tiếp." },
  { id: "l2", stable: true, text: "Card mục tiêu dưới 6 GB, nên một lúc chỉ nạp một model." },
  { id: "l3", stable: false, text: "Bản nháp này vẫn đang được viết lại cho đến khi câu đóng" },
];

export default function ComponentsPage() {
  const [speakers, setSpeakers] = useState(INITIAL_SPEAKERS);
  const [segments, setSegments] = useState(INITIAL_SEGMENTS);
  const [mode, setMode] = useState<TranscriptMode>("raw");
  const [currentMs, setCurrentMs] = useState(8_400);
  const [playing, setPlaying] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>("seg-2");
  const [notice, setNotice] = useState<string | null>(null);
  const [uploadNote, setUploadNote] = useState<string | null>(null);
  const [taskNote, setTaskNote] = useState<string | null>(null);

  useEffect(() => {
    if (!playing) return;
    const timer = window.setInterval(() => {
      setCurrentMs((value) => (value >= DURATION_MS ? 0 : value + 400));
    }, 400);
    return () => window.clearInterval(timer);
  }, [playing]);

  function rename(label: string, name: string) {
    setSpeakers((current) =>
      current.map((speaker) =>
        speaker.label === label ? { ...speaker, name, source: name === label ? speaker.source : "manual" } : speaker,
      ),
    );
  }

  function mark(marked: boolean) {
    if (!selectedId) return;
    setSegments((current) => current.map((segment) => (segment.id === selectedId ? { ...segment, marked } : segment)));
    setNotice(marked ? "Đã đánh dấu đoạn đang chọn." : "Đã bỏ đánh dấu.");
  }

  return (
    <main className="mx-auto max-w-6xl px-4 py-8 sm:px-6">
      <header className="mb-8 flex items-center gap-4">
        <img src="/logo.png" alt="" className="h-14 w-14 rounded-full object-cover" />
        <div>
          <p className="text-sm text-blue-700">Xem component</p>
          <h1 className="text-2xl font-semibold tracking-tight text-slate-900">Trợ lý biên bản họp và bài giảng</h1>
        </div>
      </header>

      <div className="space-y-10">
        <Section file="audio-uploader.tsx" title="Tải file">
          <div className="grid gap-6 lg:grid-cols-[1.2fr_0.8fr]">
            <AudioUploader
              onSubmit={({ file, vocabulary }) =>
                setUploadNote(`Đã nhận ${file.name}. Thuật ngữ: ${vocabulary || "không có"}.`)
              }
            />
            <div className="rounded-3xl bg-white/80 p-5 text-sm leading-6 text-slate-600 ring-1 ring-sky-100">
              <p>Chọn một file để nút tạo job sáng lên. Ô thuật ngữ dừng ở 800 ký tự.</p>
              {uploadNote ? <p className="mt-3 text-blue-700">{uploadNote}</p> : null}
            </div>
          </div>
        </Section>

        <Section file="audio-player-bar.tsx · speaker-list.tsx · selection-toolbar.tsx · ai-action-panel.tsx" title="Các mảnh của trang job">
          <div className="grid gap-4 lg:grid-cols-2">
            <AudioPlayerBar
              title="hop-nhom-15-10.opus"
              currentMs={currentMs}
              durationMs={DURATION_MS}
              playing={playing}
              onToggle={() => setPlaying((value) => !value)}
              onSeek={setCurrentMs}
            />
            <SpeakerList speakers={speakers} onRename={rename} />
            <SelectionToolbar
              quote="đánh dấu hoặc tạo việc"
              onMark={() => mark(true)}
              onUnmark={() => mark(false)}
              onCreateTask={() => setTaskNote("Việc mới: đánh dấu hoặc tạo việc · mốc 0:42")}
            />
            <AiActionPanel
              notice={notice}
              onNormalize={() => setNotice("Đã ghi nhận yêu cầu chuẩn hóa văn bản.")}
              onMinutes={(template: MinutesTemplate) =>
                setNotice(template === "meeting" ? "Đã chọn mẫu biên bản cuộc họp." : "Đã chọn mẫu ghi chú bài giảng.")
              }
              onExport={(format: ExportFormat) => setNotice(`Đã ghi nhận xuất ${format.toUpperCase()}.`)}
            />
          </div>
          {taskNote ? <p className="mt-3 text-sm text-blue-700">{taskNote}</p> : null}
        </Section>

        <Section file="transcript-layout.tsx" title="Trang job, hai vùng">
          <TranscriptLayout
            title="hop-nhom-15-10.opus"
            speakers={speakers}
            segments={segments}
            mode={mode}
            currentMs={currentMs}
            durationMs={DURATION_MS}
            playing={playing}
            selection={selectedId ? { segmentId: selectedId, quote: "đoạn đang chọn" } : null}
            notice={notice}
            onModeChange={setMode}
            onTogglePlay={() => setPlaying((value) => !value)}
            onSeek={setCurrentMs}
            onRenameSpeaker={rename}
            onSelect={(segmentId) => setSelectedId(segmentId)}
            onMark={() => mark(true)}
            onUnmark={() => mark(false)}
            onCreateTask={() => {
              setTaskNote("Đã tạo việc từ câu đang chọn.");
              setNotice("Đã tạo việc từ câu đang chọn.");
            }}
            onNormalize={() => setNotice("Đã ghi nhận yêu cầu chuẩn hóa văn bản.")}
            onMinutes={(template) =>
              setNotice(template === "meeting" ? "Đã chọn mẫu biên bản cuộc họp." : "Đã chọn mẫu ghi chú bài giảng.")
            }
            onExport={(format) => setNotice(`Đã ghi nhận xuất ${format.toUpperCase()}.`)}
          />
        </Section>

        <Section file="live-transcript.tsx" title="Nghe trực tiếp">
          <div className="max-w-xl">
            <LiveTranscript lines={LIVE_LINES} />
          </div>
        </Section>
      </div>
    </main>
  );
}

function Section({ file, title, children }: { file: string; title: string; children: ReactNode }) {
  return (
    <section>
      <div className="mb-3">
        <h2 className="text-lg font-semibold text-slate-900">{title}</h2>
        <p className="text-xs text-slate-400">{file}</p>
      </div>
      {children}
    </section>
  );
}
