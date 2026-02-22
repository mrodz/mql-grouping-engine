import { err, type Result } from "../../errors.js";
import { type CourseList } from "../../schema/courses/courses.js";
import type { MQLRequirement, Quantity } from "../../schema/mql/mql.js";
import { OptimizationEngine } from "../index.js";
import type { MatchingEvaluationResult } from "../matching/v1.js";

export interface PairingResult {
  requirement: MQLRequirement;
  selectedCourses: CourseList;
}

export interface OptimizationResult {
    results: PairingResult[];
}

export interface OptimizationError {
    message: string,
}

export class Optimizer extends OptimizationEngine<OptimizationResult, OptimizationError[]> {
    match(_courseList: CourseList, _from: MatchingEvaluationResult): Result<OptimizationResult, OptimizationError[]> {
        return err([{ message: 'unimplemented!',  }])
    }   
}