import { useEffect, useState } from "react";
import { Check, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  marketplaceSkillUpdateCanRetry,
  marketplaceSkillUpdateIsBusy,
  marketplaceSkillUpdateIsDisabled,
  marketplaceSkillUpdateLabel,
  marketplaceSkillUpdateStatusFromError,
  marketplaceSkillUpdateStatusFromSkill,
  type MarketplaceSkillUpdateStatus,
} from "@/lib/marketplace-skill-update";
import { fetchMarketplaceSkill, navigateToMarketplaceSkill } from "@/lib/skill-marketplace";

export function MarketplaceSkillUpdateButton({ skillId, version }: { skillId: string; version: string }) {
  const [check, setCheck] = useState(0);
  const [result, setResult] = useState<{ skillId: string; status: MarketplaceSkillUpdateStatus }>({
    skillId,
    status: "checking",
  });
  useEffect(() => {
    let active = true;
    setResult({ skillId, status: "checking" });
    fetchMarketplaceSkill(skillId).then((skill) => {
      if (!active) return;
      setResult({ skillId, status: marketplaceSkillUpdateStatusFromSkill(skill) });
    }).catch((error) => {
      if (active) setResult({ skillId, status: marketplaceSkillUpdateStatusFromError(error) });
    });
    return () => { active = false; };
  }, [skillId, version, check]);
  const status = result.skillId === skillId ? result.status : "checking";
  return (
    <Button
      type="button"
      variant="outline"
      size="sm"
      disabled={marketplaceSkillUpdateIsDisabled(status)}
      aria-busy={marketplaceSkillUpdateIsBusy(status)}
      onClick={() => marketplaceSkillUpdateCanRetry(status) ? setCheck((value) => value + 1) : navigateToMarketplaceSkill(skillId)}
    >
      {status === "current"
        ? <Check className="mr-2 h-4 w-4" aria-hidden="true" />
        : <RefreshCw className={`mr-2 h-4 w-4 ${marketplaceSkillUpdateIsBusy(status) ? "animate-spin motion-reduce:animate-none" : ""}`} aria-hidden="true" />}
      {marketplaceSkillUpdateLabel(status)}
    </Button>
  );
}
