import { exec } from "node:child_process"
import { join } from "node:path"

export default (async ({ client, directory }) => {
  return {
    event: async ({ event }) => {
      if (event.type !== "session.idle") return

      const run = () =>
        new Promise<{ code: number | null; stdout: string }>((resolve) => {
          exec("python3 selfcheck.py", { cwd: join(directory, "backend") }, (err, stdout, stderr) => {
            const out = (stdout || "") + (stderr || "")
            resolve({ code: err ? (err as { code?: number | null }).code ?? 1 : 0, stdout: out })
          })
        })

      try {
        const result = await run()
        if (result.code === 0) {
          await client.app.log({
            body: {
              service: "selfcheck",
              level: "info",
              message: "PASS — " + result.stdout.trim().split("\n").pop(),
            },
          })
        } else {
          await client.app.log({
            body: {
              service: "selfcheck",
              level: "error",
              message: "FAIL — selfcheck.py exited " + result.code + ". Known invariant regressed. See LEARNINGS.md.",
              extra: { output: result.stdout.trim() },
            },
          })
        }
      } catch (e) {
        await client.app.log({
          body: {
            service: "selfcheck",
            level: "error",
            message: "could not run selfcheck.py: " + e,
          },
        })
      }
    },
  }
})
