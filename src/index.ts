#!/usr/bin/env node
import { MQLMatcher } from "./engines/matching/v1.js";
import { CourseValidator } from "./schema/courses/validator.js";
import { MQLValidator } from "./schema/mql/validator.js"
import { mqlFiles, yaleCourses } from "./sink.js"

const MQL_PATH = "inputs/test"
const COURSES_PATH = "inputs/courses/mock_courses_2025_26.json"

const courses = await yaleCourses(COURSES_PATH, new CourseValidator());

if (!courses.ok) {
    throw courses.error;
}

const matchingEngine = new MQLMatcher();

for await (const [output, entry] of mqlFiles(MQL_PATH, new MQLValidator())) {
    if (output.ok) {
        const matchingResult = matchingEngine.match(courses.data, output.data)
        if (matchingResult.ok) {
            console.log(matchingResult.data.allSelectedCourses);
            // console.log(JSON.stringify(matchingResult.data, null, 1))
        } else {
            console.error(`❌ ${entry} could not execute: ${JSON.stringify(matchingResult.error)}`)
        }
        // console.log(`✅ ${entry} is MQL`);
    } else {
        console.error(`❌ ${entry} is not MQL: ${JSON.stringify(output.error)}`)
    }
}