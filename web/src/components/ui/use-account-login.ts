import { requestAccountLogin } from "@/lib/account";
import { useDialog } from "./use-dialog";
import { useCallback } from "react";

export function useAccountLogin() {
  const dialog = useDialog();
  return useCallback(() => requestAccountLogin(() => dialog.confirm({
    key: "account-login",
    title: "登录笔枢账户",
    message: "登录笔枢账户后即可使用公益模型、收藏、评价和投稿等功能。确认后将在浏览器打开登录页面。",
    confirmLabel: "前往登录",
  })), [dialog]);
}
