import { Loader2, LogIn, LogOut, UserRound, X } from "lucide-react";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { useAccountLogin } from "@/components/ui/use-account-login";
import { useDialog } from "@/components/ui/use-dialog";
import { useToast } from "@/components/ui/use-toast";
import {
  ACCOUNT_STATUS_EVENT,
  ACCOUNT_LOGIN_EVENT,
  AccountApiError,
  fetchAccountStatus,
  isAccountLoginPending,
  isAccountLoginCancelling,
  cancelAccountLogin,
  logoutAccount,
  type AccountStatus,
} from "@/lib/account";

export function AccountControl() {
  const login = useAccountLogin();
  const dialog = useDialog();
  const { toast } = useToast();
  const [status, setStatus] = useState<AccountStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [loginPending, setLoginPending] = useState(isAccountLoginPending);
  const [cancelling, setCancelling] = useState(isAccountLoginCancelling);
  const [available, setAvailable] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    fetchAccountStatus()
      .then((next) => {
        if (active) setStatus(next);
      })
      .catch((caught) => {
        if (!active) return;
        if (caught instanceof AccountApiError && caught.statusCode === 404) {
          setAvailable(false);
          return;
        }
        setError(caught instanceof Error ? caught.message : "无法读取账号状态");
        setStatus({ configured: true, signed_in: false });
      });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    const update = (event: Event) => {
      const detail = (event as CustomEvent<AccountStatus>).detail;
      if (detail && typeof detail.configured === "boolean" && typeof detail.signed_in === "boolean") {
        setStatus(detail);
      }
    };
    window.addEventListener(ACCOUNT_STATUS_EVENT, update);
    const updatePending = () => {
      setLoginPending(isAccountLoginPending());
      setCancelling(isAccountLoginCancelling());
    };
    window.addEventListener(ACCOUNT_LOGIN_EVENT, updatePending);
    return () => {
      window.removeEventListener(ACCOUNT_STATUS_EVENT, update);
      window.removeEventListener(ACCOUNT_LOGIN_EVENT, updatePending);
    };
  }, []);

  if (!available) return null;

  const run = async (action: () => Promise<AccountStatus>) => {
    setBusy(true);
    setError("");
    try {
      setStatus(await action());
    } catch (caught) {
      if (caught instanceof AccountApiError && ["cancelled", "authorization_denied"].includes(caught.code)) return;
      const message = caught instanceof Error ? caught.message : "账号请求失败";
      setError(message);
      toast({ title: message, variant: "error" });
    } finally {
      setBusy(false);
    }
  };

  if (status === null) {
    return (
      <Loader2
        className="h-4 w-4 shrink-0 animate-spin text-muted-foreground motion-reduce:animate-none"
        aria-label="正在加载账号状态"
      />
    );
  }

  if (!status.configured) return null;

  if (loginPending) {
    return (
      <Button
        type="button"
        variant="outline"
        size="sm"
        className="group h-9 shrink-0"
        disabled={cancelling}
        aria-label={cancelling ? "正在取消登录" : "取消登录"}
        title={cancelling ? "正在取消登录" : "取消登录"}
        onClick={() => {
          dialog.cancelMatching("account-login");
          void run(cancelAccountLogin);
        }}
      >
        <span className={cancelling ? "inline-flex items-center gap-2" : "inline-flex items-center gap-2 group-hover:hidden group-focus-visible:hidden"}>
          <Loader2 className="animate-spin motion-reduce:animate-none" aria-hidden="true" />
          {cancelling ? "正在取消" : "等待登录"}
        </span>
        {!cancelling && <span className="hidden items-center gap-2 group-hover:inline-flex group-focus-visible:inline-flex"><X aria-hidden="true" />取消登录</span>}
      </Button>
    );
  }

  if (!status.signed_in) {
    return (
      <Button
        type="button"
        variant="outline"
        size="sm"
        className="h-9 shrink-0"
        disabled={busy}
        onClick={() => void run(login)}
        title={error || "登录笔枢账户"}
      >
        {busy ? <Loader2 className="animate-spin motion-reduce:animate-none" aria-hidden="true" /> : <LogIn aria-hidden="true" />}
        登录
        {error && <span className="sr-only">：{error}</span>}
      </Button>
    );
  }

  return (
    <div className="flex shrink-0 items-center gap-1 text-sm text-muted-foreground" title={error || "DeterminFlow 账号已登录"}>
      <UserRound className="h-4 w-4" aria-hidden="true" />
      <span className="hidden 2xl:inline">已登录</span>
      <Button
        type="button"
        variant="ghost"
        size="icon"
        className="h-9 w-9 text-muted-foreground"
        disabled={busy}
        onClick={() => void run(logoutAccount)}
        aria-label="退出 DeterminFlow 账号"
        title="退出登录"
      >
        {busy ? <Loader2 className="animate-spin motion-reduce:animate-none" aria-hidden="true" /> : <LogOut aria-hidden="true" />}
      </Button>
      {error && <span className="sr-only">{error}</span>}
    </div>
  );
}
