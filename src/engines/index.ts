import type { CourseList } from "../schema/courses/courses.js";
import type { MQLQuery, MQLQueryFile } from "../schema/mql/mql.js";
import type { Result } from "../errors.js";

export abstract class CourseMatcher<M, T, E> {
    abstract match(courseList: CourseList, mql: M): Result<T, E>;
}

export abstract class MatchingEngine<T, E> extends CourseMatcher<MQLQueryFile, T, E> {
  abstract match(courseList: CourseList, mql: MQLQueryFile): Result<T, E>;
}

export abstract class QueryMatchingEngine<E> extends CourseMatcher<MQLQuery, CourseList, E> {
  abstract match(courseList: CourseList, mql: MQLQuery): Result<CourseList, E>;
}