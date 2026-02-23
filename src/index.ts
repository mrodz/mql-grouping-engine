import { writeFile } from "fs/promises";
import { MQLMatcher } from "./engines/matching/v1.js";
import { CourseValidator } from "./schema/courses/validators/v2.js";
import { MQLValidator } from "./schema/mql/validators/v1.js"
import { mqlFiles, yaleCourses } from "./sink.js"
import { exit } from "process";

let input = "";

process.stdin.setEncoding("utf8");

process.stdin.on("data", chunk => {
    input += chunk;
});

process.stdin.on("end", async () => {
    try {
        const parsed = JSON.parse(input);
        await mqlTransformer(parsed);
    } catch (err) {
        console.error("Invalid JSON input");
        console.error(err);
        process.exit(1);
    }
});

async function mqlTransformer(stdin: any) {
    const MQL_PATH = "inputs/test"
    const COURSES_PATH = "inputs/courses/courses.json"

    const courses = await yaleCourses(COURSES_PATH, new CourseValidator());

    if (!courses.ok) {
        console.error(courses.error);
        exit(1);
    }

    const courseList = courses.data;
    const matchingEngine = new MQLMatcher();

    const outputs = []

    let errc = 0;

    const mqlValidator = new MQLValidator();

    let mql;

    if (stdin.length === 0) {
        mql = mqlFiles(MQL_PATH, mqlValidator);
    } else {
        if (Array.isArray(stdin)) {
            mql = stdin.map((file, i) => {
                const res = mqlValidator.validate(file);
                return [res, `<stdin[${i}]>`] as const;
            })
        } else {
            mql = [[mqlValidator.validate(stdin), "<stdin>"] as const];
        }
    }

    for await (const [output, entry] of mql) {
        if (output.ok) {
            const matchingResult = matchingEngine.match(courseList, output.data);
            if (matchingResult.ok) {
                outputs.push(matchingResult.data);
            } else {
                console.error(`❌ ${entry} could not execute: ${JSON.stringify(matchingResult.error)}`);
                errc++;
            }
        } else {
            console.error(`❌ ${entry} is not MQL: ${JSON.stringify(output.error)}`);
            errc++;
        }
    }

    if (errc != 0) {
        exit(1);
    }

    const json = JSON.stringify(outputs);

    if (stdin.length === 0) {
        const now = +new Date();
        await writeFile(`outputs/out_${now}.txt`, json);
    }
    
    console.log(json);
}