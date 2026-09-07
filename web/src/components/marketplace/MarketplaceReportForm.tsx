import { useRef, useState } from "react";
import { Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { reportMarketplaceReview, reportMarketplaceSkill } from "@/lib/skill-marketplace";

const reasons = [
  ["security", "安全风险"], ["misleading", "信息不实"], ["copyright", "侵权"], ["spam", "垃圾内容"], ["other", "其他"],
] as const;

export function MarketplaceReportForm({ payload, onSubmitted, onCancel }: {
  payload: Record<string, unknown>;
  onSubmitted: () => void;
  onCancel: () => void;
}) {
  const [reason, setReason] = useState("security");
  const [details, setDetails] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const inFlight = useRef(false);
  const submit = async () => {
    if (inFlight.current) return;
    inFlight.current = true;
    setBusy(true);
    setError("");
    try {
      if (typeof payload.review_id === "string") {
        await reportMarketplaceReview(String(payload.slug), payload.review_id, String(payload.expected_updated_at), reason, details);
      } else {
        await reportMarketplaceSkill(String(payload.slug), reason, details);
      }
      onSubmitted();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "提交失败，请重试");
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  };
  return <form className="mt-5 space-y-4" onSubmit={(event) => { event.preventDefault(); void submit(); }}>
    <div>
      <label htmlFor="global-report-reason" className="text-sm font-medium">举报原因</label>
      <select id="global-report-reason" data-dialog-autofocus value={reason} disabled={busy} onChange={(event) => setReason(event.target.value)} className="mt-2 h-11 w-full rounded-md border border-input bg-background px-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
        {reasons.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
      </select>
    </div>
    <div>
      <label htmlFor="global-report-details" className="text-sm font-medium">补充具体情况（可选）</label>
      <textarea id="global-report-details" rows={4} maxLength={2000} value={details} disabled={busy} onChange={(event) => setDetails(event.target.value)} className="mt-2 w-full resize-y rounded-md border border-input bg-background px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" aria-describedby={error ? "global-report-error" : undefined} />
    </div>
    {error ? <p id="global-report-error" role="alert" className="text-sm text-destructive">{error}</p> : null}
    <div className="flex justify-end gap-2">
      <Button type="button" variant="outline" onClick={onCancel}>取消</Button>
      <Button type="submit" disabled={busy} aria-busy={busy}>{busy ? <Loader2 className="animate-spin motion-reduce:animate-none" aria-hidden="true" /> : null}提交举报</Button>
    </div>
  </form>;
}
