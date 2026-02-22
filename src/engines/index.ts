import type { CourseList } from "../schema/courses/courses.js";
import type { MQLQuery, MQLQueryFile } from "../schema/mql/mql.js";
import type { Result } from "../errors.js";
import type { MatchingEvaluationResult } from "./matching/v1.js";

export abstract class CourseMatcher<M, T, E> {
    abstract match(courseList: CourseList, from: M): Result<T, E>;
}

export abstract class MatchingEngine<T, E> extends CourseMatcher<MQLQueryFile, T, E> {
  abstract match(courseList: CourseList, from: MQLQueryFile): Result<T, E>;
}

export abstract class QueryMatchingEngine<E> extends CourseMatcher<MQLQuery, CourseList, E> {
  abstract match(courseList: CourseList, from: MQLQuery): Result<CourseList, E>;
}

export abstract class OptimizationEngine<T, E> extends CourseMatcher<MatchingEvaluationResult, T, E> {
  abstract match(courseList: CourseList, from: MatchingEvaluationResult): Result<T, E>;
}
