export type ConfidenceLevel = "high" | "medium" | "low";

export type Severity = "error" | "warning" | "unresolved" | "info";

export interface Diagnostic {
  code: string;
  severity: Severity;
  message: string;
  field: string | null;
}

export interface PaperSummary {
  id: number;
  course_code: string;
  course_name: string | null;
  semester: string | null;
  exam_type: string | null;
  max_marks: number | null;
  pdf_type: "vector" | "ocr_text" | "scanned";
  /** Top-level questions only; subquestions are not counted. */
  question_count: number;
  confidence: number;
  confidence_level: ConfidenceLevel;
  original_filename: string;
  created_at: string;
}

export interface QuestionOut {
  id: number;
  question_no: string;
  /** Set on a subquestion, null on a top-level question. */
  parent_no: string | null;
  text: string;
  /** Resolved total. null means it could not be read with confidence. */
  marks: number | null;
  /** Exactly what the paper printed, kept even when unresolved. */
  marks_raw: string | null;
  marks_parts: number[];
  marks_resolved: boolean;
  marks_reason: string | null;
  /** 'printed' next to the question, or 'distribution' from a paper-wide banner. */
  marks_source: string;
  recovered_label: boolean;
  module: string | null;
  co: string | null;
  bl: string | null;
  page: number | null;
}

export interface FigureOut {
  id: number;
  page: number;
  question_no: string | null;
  kind: string;
  caption: string | null;
  width_px: number | null;
  height_px: number | null;
  note: string | null;
  /** Detectors that contributed this figure's geometry. */
  sources: string[];
  /** Edges where the figure's content reaches its boundary. */
  clipped_edges: string[];
  image_url: string | null;
}

export interface PaperDetail extends PaperSummary {
  academic_year: string | null;
  slot: string | null;
  duration: string | null;
  exam_date: string | null;
  exam_time: string | null;
  marks_extracted: number;
  extraction_method: string;
  page_count: number;

  ocr_engine: string | null;
  ocr_config: string | null;
  ocr_confidence: number | null;

  confidence_breakdown: Record<string, number>;
  /** Plain messages, kept for compatibility; prefer `diagnostics`. */
  notes: string[];
  diagnostics: Diagnostic[];
  header_detail: Record<string, unknown>;
  extraction_detail: Record<string, unknown>;

  questions: QuestionOut[];
  figures: FigureOut[];
}

export interface Stats {
  total_papers: number;
  total_questions: number;
  total_courses: number;
  avg_confidence: number;
}
