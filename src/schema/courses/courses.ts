import type { UUID } from "crypto";

export interface Course {
  codes: string[];
  title: string;
  credit: number;
  dist?: string[];
  seasons: string[];
  season_codes: string[];
}

export interface ManualFulfillment {
  filled: boolean,
  id: UUID,
  description: string,
}

export type CourseList = Array<Course | ManualFulfillment>;