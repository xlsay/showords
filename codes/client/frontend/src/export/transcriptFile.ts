import type { Utterance } from "../types";

// Same two-line layout as the live display: heard text, then its translation.
export function renderTranscript(utterances: Utterance[]): string {
  const blocks = utterances.map((item) => {
    const lines = [item.text];
    if (item.translation) lines.push(item.translation);
    return lines.join("\r\n");
  });
  return blocks.join("\r\n\r\n") + "\r\n";
}

function defaultFileName(): string {
  const stamp = new Date().toISOString().slice(0, 19).replace(/[:T]/g, "-");
  return `meetingAssist_${stamp}.txt`;
}

function downloadInBrowser(name: string, content: string): void {
  const url = URL.createObjectURL(new Blob([content], { type: "text/plain;charset=utf-8" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  link.click();
  URL.revokeObjectURL(url);
}

export async function saveTranscript(utterances: Utterance[]): Promise<string | null> {
  const name = defaultFileName();
  const content = renderTranscript(utterances);
  const save = window.meetingAssist?.saveTextFile;
  if (save) return save(name, content);
  downloadInBrowser(name, content);
  return name;
}
