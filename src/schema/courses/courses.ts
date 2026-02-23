import type { UUID } from "crypto";

export interface Course {
  codes: string[];
  tags: string[];
  title: string;
  credit: number;
  dist?: string[];
  seasons: string[];
  season_codes: string[];

  /** default to v1 if empty */
  version?: string;
  external_id?: number;
  description?: string;
}

export interface ManualFulfillment {
  filled: boolean,
  id: UUID,
  description: string,
}

export type CourseList = Array<Course | ManualFulfillment>;