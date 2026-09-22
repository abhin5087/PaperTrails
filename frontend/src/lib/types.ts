export type ConfidenceLevel = "high" | "medium" | "low";

export interface PaperSummary {
  id: number;
  course_code: string;
  course_name: string | null;
  semester: string | null;
  exam_type: string | null;
  max_marks: number | null;
  pdf_type: "vector" | "ocr_text" | "scanned";
  question_count: number;
  confidence: number;
  confidence_level: ConfidenceLevel;
  original_filename: string;
  created_at: string;
}

export interface QuestionOut {
  id: number;
  question_no: string;
  text: string;
  marks: number | null;
  module: string | null;
  co: string | null;
  bl: string | null;
  page: number | null;
}

export interface PaperDetail extends PaperSummary {
  academic_year: string | null;
  slot: string | null;
  duration: string | null;
  exam_date: string | null;
  marks_extracted: number;
  extraction_method: string;
  confidence_breakdown: Record<string, number>;
  notes: string[];
  questions: QuestionOut[];
}

export interface Stats {
  total_papers: number;
  total_questions: number;
  total_courses: number;
  avg_confidence: number;
}
