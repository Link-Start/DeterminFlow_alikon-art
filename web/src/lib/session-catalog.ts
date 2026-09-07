import type { Session } from "../types";

export type SessionCategory = "main" | "workflow" | "assistant";

export function sessionCategory(session: Session): SessionCategory {
  if (session.lifecycle_profile === "detached_conversation") return "assistant";
  if (
    session.runtime_scope === "workflow" ||
    (session.type === "main" && (session.task || "").startsWith("Workflow:"))
  ) {
    return "workflow";
  }
  return "main";
}

export function partitionSessions(sessions: Session[]) {
  const mains = sessions.filter((session) => session.type === "main");
  const subs = sessions.filter((session) => session.type === "sub");
  return {
    groups: mains.map((main) => ({
      main,
      category: sessionCategory(main),
      subs: subs.filter(
        (session) =>
          session.parent_id === main.session_id &&
          sessionCategory(session) !== "assistant",
      ),
    })),
    assistants: sessions.filter(
      (session) => sessionCategory(session) === "assistant",
    ),
  };
}
