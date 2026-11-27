export type LanguageCode = "zh" | "en";
export type DetectedLanguage = LanguageCode | "unknown";
export type SessionState = "starting" | "running" | "ended";
export type AudioSourceName = "microphone" | "system";

export interface Utterance {
  id: string;
  index: number;
  startTime: number;
  endTime: number;
  language: DetectedLanguage;
  text: string;
  targetLanguage: LanguageCode | null;
  translation: string | null;
}

export interface UtterancePayload {
  id: string;
  index: number;
  start_time: number;
  end_time: number;
  language: DetectedLanguage;
  text: string;
  target_language: LanguageCode | null;
}

export interface TranslationPayload {
  id: string;
  target_language: LanguageCode;
  translation: string;
}

export interface SessionStatePayload {
  state: SessionState;
  source: AudioSourceName;
  elapsed_seconds: number;
  utterance_count: number;
}

export interface ErrorPayload {
  code: string;
  message: string;
}

export type ServerEvent =
  | { type: "session_state"; payload: SessionStatePayload }
  | { type: "utterance"; payload: UtterancePayload }
  | { type: "translation"; payload: TranslationPayload }
  | { type: "error"; payload: ErrorPayload };
