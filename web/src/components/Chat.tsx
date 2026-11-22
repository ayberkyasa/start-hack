import { useEffect, useRef, type ReactNode } from "react"
import { cn } from "@/lib/utils"
import type { SimEvent, ThemEvent } from "@/types"

function SystemLine({ children, tone = "muted" }: { children: ReactNode; tone?: "muted" | "error" | "success" }) {
  return (
    <div className="flex justify-center my-1">
      <div
        className={cn(
          "text-xs rounded-full px-3 py-1 max-w-[80%] text-center",
          tone === "muted" && "bg-muted text-muted-foreground",
          tone === "error" && "bg-destructive/10 text-destructive",
          tone === "success" && "bg-emerald-600/15 text-emerald-700 dark:text-emerald-400 font-medium"
        )}
      >
        {children}
      </div>
    </div>
  )
}

function ChannelBadge({ channel }: { channel?: string }) {
  if (!channel) return null
  return (
    <span className="inline-flex items-center rounded-full border border-current/40 px-1.5 h-4 text-[10px] text-current opacity-80">
      {channel}
    </span>
  )
}

function ThemItem({ e }: { e: ThemEvent }) {
  if (e.type === "reply") {
    return (
      <div className="flex justify-start">
        <div className="max-w-[78%] rounded-2xl rounded-tl-sm bg-muted px-3 py-2 text-sm">
          <div className="flex items-center gap-2 mb-1 text-muted-foreground">
            <span className="font-medium text-foreground">Target</span>
            <ChannelBadge channel={e.channel} />
          </div>
          {e.subject && <div className="font-medium mb-0.5">{e.subject}</div>}
          <div className="whitespace-pre-wrap">{e.body}</div>
        </div>
      </div>
    )
  }
  if (e.type === "link.opened") return <SystemLine>🔗 opened link — {e.url}</SystemLine>
  if (e.type === "attachment.opened") return <SystemLine tone="success">📎 opened attachment</SystemLine>
  if (e.type === "page.submitted") {
    const vals = e.values || {}
    const shown = Object.entries(vals).map(([k, v]) => `${k}: ${v}`).join(" · ")
    return (
      <SystemLine tone="success">
        📝 submitted form [{(e.fields || []).join(", ")}]{shown ? ` — ${shown}` : ""}
      </SystemLine>
    )
  }
  return <SystemLine>event: {e.type}</SystemLine>
}

export default function Chat({ events, running }: { events: SimEvent[]; running?: boolean }) {
  const endRef = useRef<HTMLDivElement>(null)
  useEffect(() => { endRef.current?.scrollIntoView({ behavior: "smooth" }) }, [events, running])

  return (
    <div className="flex flex-col gap-3">
      {events.map((ev, i) => {
        if (ev.kind === "status") return <SystemLine key={i}>{ev.text}</SystemLine>
        if (ev.kind === "error") return <SystemLine key={i} tone="error">⚠ {ev.text}</SystemLine>
        if (ev.kind === "won")
          return <SystemLine key={i} tone="success">✅ Objective won: {ev.objectives.join(", ")}</SystemLine>
        if (ev.kind === "research")
          return (
            <details key={i} className="mx-auto w-full rounded-lg border bg-muted/40 px-3 py-2 text-xs">
              <summary className="cursor-pointer text-muted-foreground select-none">🔎 Recon brief (click to expand)</summary>
              <pre className="mt-2 whitespace-pre-wrap font-sans">{ev.text}</pre>
            </details>
          )
        if (ev.kind === "them") {
          if (!ev.events.length) return <SystemLine key={i}>target ignored — no reaction</SystemLine>
          return <div key={i} className="flex flex-col gap-2">{ev.events.map((e, j) => <ThemItem key={j} e={e} />)}</div>
        }
        if (ev.kind === "us") {
          return (
            <div key={i} className="flex justify-end">
              <div className="max-w-[78%] rounded-2xl rounded-tr-sm border border-primary bg-primary/10 text-foreground px-3 py-2 text-sm">
                <div className="flex items-center gap-2 mb-1 text-muted-foreground">
                  <span className="font-medium text-foreground">Us · touch {ev.touch}</span>
                  <ChannelBadge channel={ev.channel} />
                </div>
                {ev.from && (
                  <div className="text-xs text-muted-foreground mb-1">
                    from {ev.from.name}{ev.from.address ? ` <${ev.from.address}>` : ""}
                  </div>
                )}
                {ev.subject && <div className="font-semibold mb-0.5">{ev.subject}</div>}
                <div className="whitespace-pre-wrap">{ev.body}</div>
                {ev.page && (
                  <div className="mt-2 rounded-md border border-primary/40 bg-primary/5 px-2 py-1 text-xs">
                    📄 landing page: {ev.page.title || ev.page.url}
                    {ev.page.fields?.length ? ` — fields [${ev.page.fields.join(", ")}]` : ""}
                  </div>
                )}
                {ev.rationale && <div className="text-xs italic text-muted-foreground mt-1">why: {ev.rationale}</div>}
              </div>
            </div>
          )
        }
        return null
      })}
      {running && <SystemLine>● agent is working…</SystemLine>}
      <div ref={endRef} />
    </div>
  )
}
