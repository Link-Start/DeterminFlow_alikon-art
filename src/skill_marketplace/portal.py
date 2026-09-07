"""HTTP client for the DeterminFlow Resource Marketplace contract."""

from __future__ import annotations

import ipaddress
from typing import Any
from urllib.parse import urlparse

import httpx

from .errors import normalize_retry_after_seconds

DEFAULT_MARKETPLACE_URL = "https://determinflow.com"
class MarketplaceRequestError(RuntimeError):
    """A marketplace failure that is safe to return to the desktop UI."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 502,
        retry_after_seconds: int | None = None,
    ):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.retry_after_seconds = normalize_retry_after_seconds(retry_after_seconds)


_EMBED_PATH = "/embed/marketplace"


def is_allowed_marketplace_url(value: str, *, allow_loopback_http: bool = False) -> bool:
    parsed = urlparse(value)
    if (
        not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        return False
    if parsed.scheme == "https":
        return True
    if not allow_loopback_http or parsed.scheme != "http" or not parsed.hostname:
        return False
    if parsed.hostname == "localhost":
        return True
    try:
        return ipaddress.ip_address(parsed.hostname).is_loopback
    except ValueError:
        return False


def resolve_marketplace_embed_url(
    marketplace_url: str | None,
    *,
    override: str | None = None,
    allow_loopback_http: bool = False,
) -> str:
    """Return a validated iframe src for the official marketplace embed.

    DETERMINFLOW_MARKETPLACE_EMBED_URL may independently override the default,
    which is DETERMINFLOW_MARKETPLACE_URL with `/embed/marketplace` appended.
    """
    candidate = (override or "").strip().rstrip("/")
    if not candidate:
        base = (marketplace_url or "").strip().rstrip("/")
        if not base:
            raise ValueError("资源广场嵌入地址无法从空的官网地址生成")
        candidate = f"{base}{_EMBED_PATH}"
    if not is_allowed_marketplace_url(
        candidate,
        allow_loopback_http=allow_loopback_http,
    ):
        raise ValueError("资源广场嵌入地址必须是 HTTPS 或显式允许的本机 HTTP 地址")
    return candidate


class ResourceMarketplaceClient:
    """Small, typed boundary around the public marketplace API."""

    def __init__(
        self,
        base_url: str,
        *,
        app_version: str,
        allow_loopback_http: bool = False,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        normalized = base_url.strip().rstrip("/")
        if not is_allowed_marketplace_url(
            normalized,
            allow_loopback_http=allow_loopback_http,
        ):
            raise ValueError("资源广场地址必须是 HTTPS 地址")
        self.base_url = normalized
        self.app_version = app_version.strip() or "unknown"
        self.transport = transport

    async def list_skills(
        self,
        *,
        query: str = "",
        category: str = "all",
        sort: str = "updated",
    ) -> dict[str, Any]:
        params = {
            key: value
            for key, value in {
                "q": query.strip(),
                "category": category.strip(),
                "sort": sort.strip(),
            }.items()
            if value and value != "all"
        } or None
        body = await self._request_json(
            "GET",
            "/api/resource-marketplace/skills",
            params=params,
        )
        if not isinstance(body, dict) or not isinstance(body.get("items"), list):
            raise MarketplaceRequestError("invalid_response", "Skill 广场返回了无效列表")
        return body

    async def list_skill_page(
        self,
        *,
        query: str = "",
        category: str = "all",
        sort: str = "updated",
        page: int = 1,
        page_size: int = 24,
        favorites: bool = False,
        access_token: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "page": page,
            "page_size": page_size,
        }
        if query.strip():
            params["q"] = query.strip()
        if category.strip() and category.strip() != "all":
            params["category"] = category.strip()
        if sort.strip() and sort.strip() != "updated":
            params["sort"] = sort.strip()
        if favorites:
            params["favorites"] = "true"
        else:
            params["favorites"] = "false"
            access_token = None
        body = await self._request_json(
            "GET",
            "/api/resource-marketplace/catalog/skills",
            params=params,
            access_token=access_token,
        )
        if (
            not isinstance(body, dict)
            or not isinstance(body.get("items"), list)
            or not isinstance(body.get("total"), int)
            or not isinstance(body.get("page"), int)
            or not isinstance(body.get("page_size"), int)
        ):
            raise MarketplaceRequestError("invalid_response", "Skill 广场返回了无效分页")
        return body

    async def preview_skill(
        self,
        slug: str,
        *,
        expected_version_id: str,
        expected_sha256: str,
    ) -> dict[str, Any]:
        body = await self._request_json(
            "GET",
            f"/api/resource-marketplace/skills/{slug}/preview",
            params={
                "expected_version_id": expected_version_id,
                "expected_sha256": expected_sha256,
            },
        )
        if not isinstance(body, dict):
            raise MarketplaceRequestError("invalid_response", "Skill 广场返回了无效预览")
        return body

    async def list_community_reviews(self, slug: str) -> dict[str, Any]:
        body = await self._request_json(
            "GET",
            f"/api/resource-marketplace/skills/{slug}/reviews",
        )
        if not isinstance(body, dict) or not isinstance(body.get("items"), list):
            raise MarketplaceRequestError("invalid_response", "资源广场返回了无效评价列表")
        return body

    async def list_community_review_page(
        self,
        slug: str,
        *,
        page: int = 1,
        page_size: int = 20,
    ) -> dict[str, Any]:
        body = await self._request_json(
            "GET",
            f"/api/resource-marketplace/skills/{slug}/reviews/page",
            params={"page": page, "page_size": page_size},
        )
        return self._validated_page(body, "资源广场返回了无效评价分页")

    async def get_community_state(
        self,
        slug: str,
        *,
        access_token: str,
    ) -> dict[str, Any]:
        return await self._request_object(
            f"/api/resource-marketplace/skills/{slug}/community",
            access_token=access_token,
            invalid_message="资源广场返回了无效社区状态",
        )

    async def set_favorite(
        self,
        slug: str,
        *,
        favorited: bool,
        access_token: str,
    ) -> dict[str, Any]:
        return await self._request_object(
            f"/api/resource-marketplace/skills/{slug}/favorite",
            method="PUT" if favorited else "DELETE",
            access_token=access_token,
            invalid_message="资源广场返回了无效收藏结果",
        )

    async def upsert_community_review(
        self,
        slug: str,
        *,
        rating: int,
        body: str,
        access_token: str,
    ) -> dict[str, Any]:
        return await self._request_object(
            f"/api/resource-marketplace/skills/{slug}/review",
            method="PUT",
            json={"rating": rating, "body": body},
            access_token=access_token,
            invalid_message="资源广场返回了无效评价结果",
        )

    async def delete_community_review(
        self,
        slug: str,
        *,
        review_id: str,
        expected_updated_at: str,
        access_token: str,
    ) -> dict[str, Any]:
        body = await self._request_object(
            f"/api/resource-marketplace/skills/{slug}/review",
            method="DELETE",
            json={
                "review_id": review_id,
                "expected_updated_at": expected_updated_at,
            },
            access_token=access_token,
            invalid_message="资源广场返回了无效删除结果",
        )
        if body.get("deleted") is not True:
            raise MarketplaceRequestError(
                "invalid_response",
                "资源广场返回了无效删除结果",
            )
        return body

    async def report_skill(
        self,
        slug: str,
        *,
        reason: str,
        details: str,
        access_token: str,
    ) -> dict[str, Any]:
        return await self._request_object(
            f"/api/resource-marketplace/skills/{slug}/report",
            method="POST",
            json={"reason": reason, "details": details},
            access_token=access_token,
            invalid_message="资源广场返回了无效举报结果",
        )

    async def report_community_review(
        self,
        slug: str,
        review_id: str,
        *,
        expected_updated_at: str,
        reason: str,
        details: str,
        access_token: str,
    ) -> dict[str, Any]:
        body = await self._request_object(
            f"/api/resource-marketplace/skills/{slug}/reviews/{review_id}/report",
            method="POST",
            json={
                "expected_updated_at": expected_updated_at,
                "reason": reason,
                "details": details,
            },
            access_token=access_token,
            invalid_message="资源广场返回了无效举报结果",
        )
        if body.get("reported") is not True:
            raise MarketplaceRequestError(
                "invalid_response",
                "资源广场返回了无效举报结果",
            )
        return body

    async def get_skill(self, slug: str) -> dict[str, Any]:
        body = await self._request_json(
            "GET",
            f"/api/resource-marketplace/skills/{slug}",
        )
        if not isinstance(body, dict):
            raise MarketplaceRequestError("invalid_response", "Skill 广场返回了无效详情")
        return body

    async def download_skill(self, slug: str) -> tuple[bytes, str | None]:
        response = await self._request(
            "GET",
            f"/api/resource-marketplace/skills/{slug}/download",
        )
        return response.content, response.headers.get("x-skill-sha256")

    async def publish_skill(
        self,
        *,
        content: bytes,
        license_id: str,
        rights_confirmed: bool,
        resource_type: str,
        metadata: dict[str, Any],
        terms_confirmed: bool,
        terms_version: str,
        access_token: str,
        target_slug: str | None = None,
        publication_version: str | None = None,
    ) -> dict[str, Any]:
        try:
            raw_content = content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise MarketplaceRequestError(
                "invalid_skill",
                "SKILL.md 必须是 UTF-8 文本",
                status_code=422,
            ) from exc
        payload: dict[str, Any] = {
            "content": raw_content,
            "license": license_id,
            "rights_confirmed": rights_confirmed,
            "resource_type": resource_type,
            "metadata": metadata,
            "terms_confirmed": terms_confirmed,
            "terms_version": terms_version,
        }
        if target_slug:
            payload["target_slug"] = target_slug
        if publication_version:
            payload["publication_version"] = publication_version
        body = await self._request_json(
            "POST",
            "/api/resource-marketplace/skills",
            json=payload,
            access_token=access_token,
        )
        if not isinstance(body, dict):
            raise MarketplaceRequestError("invalid_response", "Skill 广场返回了无效上传结果")
        return body

    async def check_resource_names(
        self,
        slugs: list[str],
        *,
        access_token: str,
    ) -> dict[str, Any]:
        body = await self._request_json(
            "POST",
            "/api/resource-marketplace/name-check",
            json={"resource_type": "skill", "slugs": slugs},
            access_token=access_token,
        )
        if not isinstance(body, dict) or not isinstance(body.get("items"), list):
            raise MarketplaceRequestError("invalid_response", "资源广场返回了无效名称检查结果")
        return body

    async def list_author_resources(
        self,
        *,
        query: str = "",
        status: str = "all",
        page: int = 1,
        page_size: int = 20,
        access_token: str,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"page": page, "page_size": page_size}
        if query.strip():
            params["q"] = query.strip()
        if status.strip() and status.strip() != "all":
            params["status"] = status.strip()
        return await self._request_page(
            "/api/resource-marketplace/author/resources",
            access_token=access_token,
            params=params,
            invalid_message="资源广场返回了无效作者资源分页",
        )

    async def list_author_versions(
        self,
        slug: str,
        *,
        page: int = 1,
        page_size: int = 20,
        access_token: str,
    ) -> dict[str, Any]:
        return await self._request_page(
            f"/api/resource-marketplace/author/resources/{slug}/versions",
            access_token=access_token,
            params={"page": page, "page_size": page_size},
            invalid_message="资源广场返回了无效作者版本分页",
        )

    async def list_feedback(
        self,
        *,
        page: int = 1,
        page_size: int = 20,
        unread_only: bool = False,
        access_token: str,
    ) -> dict[str, Any]:
        return await self._request_page(
            "/api/resource-marketplace/feedback",
            access_token=access_token,
            params={
                "page": page,
                "page_size": page_size,
                "unread_only": "true" if unread_only else "false",
            },
            extra_ints=("unread_total",),
            invalid_message="资源广场返回了无效反馈分页",
        )

    async def mark_feedback_read(
        self,
        *,
        feedback_id: str,
        expected_updated_at: str,
        access_token: str,
    ) -> dict[str, Any]:
        return await self._request_object(
            "/api/resource-marketplace/feedback/read",
            method="POST",
            json={"id": feedback_id, "expected_updated_at": expected_updated_at},
            access_token=access_token,
            invalid_message="资源广场返回了无效已读结果",
        )

    async def list_submissions(self, *, access_token: str) -> dict[str, Any]:
        return await self._request_item_list(
            "/api/resource-marketplace/submissions",
            access_token=access_token,
            invalid_message="Skill 广场返回了无效投稿列表",
        )

    async def get_submission(self, version_id: str, *, access_token: str) -> dict[str, Any]:
        return await self._request_object(
            f"/api/resource-marketplace/submissions/{version_id}",
            access_token=access_token,
            invalid_message="Skill 广场返回了无效投稿详情",
        )

    async def withdraw_submission(
        self,
        version_id: str,
        *,
        access_token: str,
    ) -> dict[str, Any]:
        return await self._request_object(
            f"/api/resource-marketplace/submissions/{version_id}/withdraw",
            method="POST",
            access_token=access_token,
            invalid_message="Skill 广场返回了无效撤回结果",
        )

    async def list_review_queue(self, *, access_token: str) -> dict[str, Any]:
        return await self._request_item_list(
            "/api/resource-marketplace/review-queue",
            access_token=access_token,
            invalid_message="Skill 广场返回了无效审核队列",
        )

    async def get_review_item(self, version_id: str, *, access_token: str) -> dict[str, Any]:
        return await self._request_object(
            f"/api/resource-marketplace/review-queue/{version_id}",
            access_token=access_token,
            invalid_message="Skill 广场返回了无效审核详情",
        )

    async def review_version(
        self,
        version_id: str,
        *,
        decision: str,
        expected_sha256: str,
        reason: str | None,
        access_token: str,
        expected_current_version_id: str | None = None,
        expected_current_version_provided: bool = False,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "decision": decision,
            "expected_sha256": expected_sha256,
        }
        if reason is not None:
            payload["reason"] = reason
        if expected_current_version_provided or expected_current_version_id is not None:
            payload["expected_current_version_id"] = expected_current_version_id
        return await self._request_object(
            f"/api/resource-marketplace/reviews/{version_id}",
            method="POST",
            json=payload,
            access_token=access_token,
            invalid_message="Skill 广场返回了无效审核结果",
        )

    async def suspend_skill(
        self,
        slug: str,
        *,
        expected_version_id: str,
        reason: str,
        access_token: str,
    ) -> dict[str, Any]:
        return await self._request_object(
            f"/api/resource-marketplace/skills/{slug}/suspend",
            method="POST",
            json={
                "expected_version_id": expected_version_id,
                "reason": reason,
            },
            access_token=access_token,
            invalid_message="Skill 广场返回了无效下架结果",
        )

    async def resume_skill(
        self,
        slug: str,
        *,
        expected_version_id: str,
        reason: str,
        access_token: str,
    ) -> dict[str, Any]:
        return await self._request_object(
            f"/api/resource-marketplace/skills/{slug}/resume",
            method="POST",
            json={
                "expected_version_id": expected_version_id,
                "reason": reason,
            },
            access_token=access_token,
            invalid_message="Skill 广场返回了无效恢复上架结果",
        )

    async def update_skill_lifecycle(
        self,
        slug: str,
        *,
        deprecated: bool,
        replacement_slug: str | None,
        message: str | None,
        access_token: str,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"deprecated": deprecated}
        if replacement_slug is not None:
            payload["replacement_slug"] = replacement_slug
        if message is not None:
            payload["message"] = message
        return await self._request_object(
            f"/api/resource-marketplace/skills/{slug}/lifecycle",
            method="PATCH",
            json=payload,
            access_token=access_token,
            invalid_message="Skill 广场返回了无效生命周期结果",
        )

    async def _request_page(
        self,
        path: str,
        *,
        access_token: str,
        invalid_message: str,
        params: dict[str, Any] | None = None,
        extra_ints: tuple[str, ...] = (),
    ) -> dict[str, Any]:
        body = await self._request_item_list(
            path,
            access_token=access_token,
            invalid_message=invalid_message,
            params=params,
        )
        return self._validated_page(body, invalid_message, extra_ints=extra_ints)

    @staticmethod
    def _validated_page(
        body: Any,
        invalid_message: str,
        extra_ints: tuple[str, ...] = (),
    ) -> dict[str, Any]:
        if not isinstance(body, dict) or not isinstance(body.get("items"), list):
            raise MarketplaceRequestError("invalid_response", invalid_message)
        for key in ("total", "page", "page_size", *extra_ints):
            value = body.get(key)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise MarketplaceRequestError("invalid_response", invalid_message)
        if (
            not 1 <= body["page"] <= 100_000
            or not 1 <= body["page_size"] <= 100
            or len(body["items"]) > body["page_size"]
        ):
            raise MarketplaceRequestError("invalid_response", invalid_message)
        return body

    async def _request_item_list(
        self,
        path: str,
        *,
        access_token: str,
        invalid_message: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        request_kwargs: dict[str, Any] = {"access_token": access_token}
        if params:
            request_kwargs["params"] = params
        body = await self._request_json("GET", path, **request_kwargs)
        if not isinstance(body, dict) or not isinstance(body.get("items"), list):
            raise MarketplaceRequestError("invalid_response", invalid_message)
        return body

    async def _request_object(
        self,
        path: str,
        *,
        access_token: str,
        invalid_message: str,
        method: str = "GET",
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        request_kwargs: dict[str, Any] = {"access_token": access_token}
        if json is not None:
            request_kwargs["json"] = json
        body = await self._request_json(method, path, **request_kwargs)
        if not isinstance(body, dict):
            raise MarketplaceRequestError("invalid_response", invalid_message)
        return body

    async def _request_json(self, method: str, path: str, **kwargs: Any) -> Any:
        return self._decode_json(await self._request(method, path, **kwargs))

    async def _request(
        self,
        method: str,
        path: str,
        *,
        access_token: str | None = None,
        **kwargs: Any,
    ) -> httpx.Response:
        headers = {
            "Accept": "application/json",
            "User-Agent": f"DeterminFlow-Resource-Marketplace/{self.app_version}",
        }
        if access_token:
            headers["Authorization"] = f"Bearer {access_token}"
        try:
            async with httpx.AsyncClient(
                base_url=self.base_url,
                timeout=httpx.Timeout(15.0, connect=5.0),
                follow_redirects=False,
                transport=self.transport,
            ) as client:
                response = await client.request(
                    method,
                    path,
                    headers=headers,
                    **kwargs,
                )
        except httpx.RequestError as exc:
            raise MarketplaceRequestError(
                "network_unavailable",
                "暂时无法连接资源广场",
            ) from exc
        if response.status_code < 400:
            return response
        message = self._error_message(response)
        if response.status_code == 400:
            code = self._error_code(response)
            allowed = {"invalid_review", "invalid_review_id", "invalid_report", "invalid_request", "invalid_pagination", "invalid_query"}
            raise MarketplaceRequestError(
                code if code in allowed else "invalid_request",
                message or "请求参数无效，请检查后重试",
                status_code=400,
            )
        if response.status_code == 401:
            raise MarketplaceRequestError(
                "authentication_failed",
                "资源广场登录状态已失效",
                status_code=401,
            )
        if response.status_code == 403:
            raise MarketplaceRequestError(
                "forbidden",
                message or "没有权限执行该操作",
                status_code=403,
            )
        if response.status_code == 404:
            raise MarketplaceRequestError("not_found", message or "Skill 不存在", status_code=404)
        if response.status_code == 409:
            code = self._error_code(response)
            known = {
                "version_changed": "资源版本已变化，请刷新详情后重新确认",
                "feedback_changed": "反馈状态已变化，请刷新后重试",
                "review_changed": "评价已变化，请刷新后重试",
                "review_conflict": "审核对照版本已变化，请刷新后重试",
                "withdraw_conflict": "当前投稿不能撤回",
                "local_skill_changed": "本地 Skill 已变化，请重新预览后提交",
                "draft_conflict": "草稿已被更新，请刷新后重试",
            }
            if code in known:
                raise MarketplaceRequestError(
                    code,
                    message or known[code],
                    status_code=409,
                )
            raise MarketplaceRequestError("conflict", message or "Skill 版本冲突", status_code=409)
        if response.status_code == 413:
            raise MarketplaceRequestError("too_large", "SKILL.md 超出大小限制", status_code=413)
        if response.status_code == 422:
            raise MarketplaceRequestError("invalid_skill", message or "SKILL.md 校验失败", status_code=422)
        if response.status_code == 429:
            raise MarketplaceRequestError(
                "rate_limited",
                message or "请求过于频繁，请稍后重试",
                status_code=429,
                retry_after_seconds=self._retry_after_seconds(response),
            )
        raise MarketplaceRequestError(
            "service_unavailable",
            message or "资源广场服务暂不可用",
            status_code=502,
        )

    @staticmethod
    def _decode_json(response: httpx.Response) -> Any:
        try:
            return response.json()
        except ValueError as exc:
            raise MarketplaceRequestError(
                "invalid_response",
                "资源广场返回了无效响应",
            ) from exc

    @classmethod
    def _retry_after_seconds(cls, response: httpx.Response) -> int | None:
        body = cls._error_body(response) or {}
        detail = body.get("detail")
        nested = detail.get("retry_after_seconds") if isinstance(detail, dict) else None
        for candidate in (
            body.get("retry_after_seconds"),
            nested,
            response.headers.get("Retry-After"),
        ):
            seconds = normalize_retry_after_seconds(candidate)
            if seconds is not None:
                return seconds
        return None

    @classmethod
    def _error_code(cls, response: httpx.Response) -> str | None:
        body = cls._error_body(response)
        if body is None:
            return None
        code = body.get("code")
        if isinstance(code, str) and code.strip():
            return code.strip()
        detail = body.get("detail")
        if isinstance(detail, dict):
            nested = detail.get("code")
            if isinstance(nested, str) and nested.strip():
                return nested.strip()
        return None

    @classmethod
    def _error_message(cls, response: httpx.Response) -> str | None:
        body = cls._error_body(response)
        if body is None:
            return None
        detail = body.get("detail") or body.get("message")
        if isinstance(detail, str) and detail.strip():
            return detail.strip()
        if isinstance(detail, dict):
            nested = detail.get("message") or detail.get("detail")
            if isinstance(nested, str) and nested.strip():
                return nested.strip()
        return None

    @staticmethod
    def _error_body(response: httpx.Response) -> dict[str, Any] | None:
        try:
            body = response.json()
        except ValueError:
            return None
        return body if isinstance(body, dict) else None
