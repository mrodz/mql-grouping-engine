import { readdir, readFile } from "fs/promises";
import { err, ok, type Result } from "./errors.js";
import type { MQLQueryFile } from "./schema/mql/mql.js";
import path from "path";
import type { CourseList } from "./schema/courses/courses.js";
import type { Validator } from "./schema/index.js";

export async function* mqlFiles<E>(dirpath: string, validator: Validator<MQLQueryFile, E>): AsyncGenerator<[Result<MQLQueryFile, E | string>, string], Result<undefined, string>> {
    let dir;
    try {
        dir = await readdir(dirpath, { withFileTypes: true });
    } catch (e) {
        return err(`could not read directory: ${dirpath}: ${e}`);
    }

    for (const d of dir) {
        const entry = path.join(dirpath, d.name);

        if (d.isFile()) {
            if (d.name.endsWith(".json")) {
                let file;
                try {
                    file = await readFile(entry, 'utf-8');
                } catch (e) {
                    yield [err(`could not read file: ${e}`), entry];
                    continue;
                }

                let jsonNode;
                try {
                    jsonNode = JSON.parse(file);
                } catch (e) {
                    yield [err(`could not parse JSON in ${entry}: ${e}`), entry];
                    continue;
                }

                const output = validator.validate(jsonNode);

                yield [output, entry]
            }
        }
    }

    return ok()
}

export async function yaleCourses<E>(filepath: string, validator: Validator<CourseList, E>): Promise<Result<CourseList, E | string>> {
    if (!filepath.endsWith(".json")) {
        return err("filepath should end with .json");
    }

    let file;
    try {
        file = await readFile(filepath, 'utf-8');
    } catch (e) {
        return err(`could not open file ${filepath}: ${e}`)
    }

    let jsonNode;
    try {
        jsonNode = JSON.parse(file);
    } catch (e) {
        return err(`could not parse JSON in ${filepath}: ${e}`)
    }

    return validator.validate(jsonNode)
}