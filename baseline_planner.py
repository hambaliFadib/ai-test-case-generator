"""Deterministic QA baseline evaluation for the locked baseline contract.

Three layers stay strictly separated:

1. QA baseline policy  — the fixed, ordered, versioned rule table below,
   owned by the application. It defines which baseline dimensions exist and
   what product evidence/policy can support them.
2. Product evidence    — requirement-local evidence atoms extracted from the
   source document.
3. Product policy      — explicit product statements (constraints and numeric
   limits) that can supply concreteness the evidence does not.

A baseline dimension follows:

    NOT_APPLICABLE -> APPLICABLE_UNRESOLVED -> MATERIALIZABLE -> MATERIALIZED

Applicable dimensions that product evidence or product policy cannot support
are retained as UnresolvedBaselineItem records. Nothing is ever dropped
silently, and nothing here may invent product behavior.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re

from models.coverage_model import EvidenceAtom, UnresolvedBaselineItem
from models.requirement_model import Requirement


BASELINE_CONTRACT_VERSION = 2

STATUS_NOT_APPLICABLE = "NOT_APPLICABLE"
STATUS_APPLICABLE_UNRESOLVED = "APPLICABLE_UNRESOLVED"
STATUS_MATERIALIZABLE = "MATERIALIZABLE"
STATUS_MATERIALIZED = "MATERIALIZED"

DISPOSITION_RETAINED = "retained"

_POLICY_SOURCE = "product_policy"
_EVIDENCE_SOURCE = "product_evidence"


@dataclass(frozen=True)
class BaselineRule:
    """One ordered, versioned baseline dimension and its evidence boundary."""

    rule_key: str
    dimension: str
    positive: re.Pattern
    reason: str
    version: int = 1
    related: re.Pattern | None = None
    negation: re.Pattern | None = None
    scope: re.Pattern | None = None
    scope_exclusion: re.Pattern | None = None
    evidence_kinds: tuple[str, ...] = ()
    requires_policy: bool = True


@dataclass(frozen=True)
class BaselineDomain:
    """An applicable baseline family with a fixed, ordered rule list."""

    key: str
    applicability: re.Pattern
    rules: tuple[BaselineRule, ...]


@dataclass
class BaselineEvaluation:
    """Deterministic outcome of evaluating one requirement's baselines."""

    materialized: list[tuple[str, str]] = field(default_factory=list)
    not_applicable: list[str] = field(default_factory=list)
    unresolved: list[UnresolvedBaselineItem] = field(default_factory=list)
    policy_candidates: list[tuple[str, str, str, str]] = field(default_factory=list)


_CREDENTIAL_INVALID = re.compile(
    r"(?=[^\n]*\b(?:credential\w*|password\w*|passcode|username|user\s?name|login)\b)"
    r"(?=[^\n]*\b(?:invalid|wrong|incorrect|rejected|unknown|failed|not\s+found)\b)",
    re.IGNORECASE,
)
_CREDENTIAL_REQUIRED = re.compile(
    r"(?=[^\n]*\b(?:credential\w*|password\w*|passcode|username|user\s?name|login)\b)"
    r"(?=[^\n]*\b(?:empty|blank|required|mandatory|omitted|missing|must\s+be\s+provided|"
    r"cannot\s+be\s+empty|validation)\b)",
    re.IGNORECASE,
)
_FIELD_EMPTY = (
    r"(?=[^\n]*\b(?:empty|blank|required|mandatory|omitted|missing|must\s+be\s+provided|"
    r"cannot\s+be\s+empty|validation)\b)"
)
_LOGOUT = r"\b(?:logs?[\s-]?out|signs?[\s-]?out|logout)\b"
_SESSION_BEHAVIOR = (
    r"(?=[^\n]*\bsession\b)"
    r"(?=[^\n]*\b(?:expire\w*|expiry|timeout|time-out|duration|lasts?|until|valid|idle|"
    r"refresh\w*|revoke\w*|invalidat\w*|ends?|signed\s+in|tokens?)\b)"
)

AUTH_DOMAIN = re.compile(
    r"\b(?:"
    r"logs?[\s-]?in|signs?[\s-]?in|authenticat\w*|credential\w*|password\w*|passcode|"
    r"username|user\s?name|account\w*\s+(?:is\s+)?(?:lock\w*|disabled|suspended)|"
    r"failed\s+attempt\w*|too\s+many\s+attempts?|"
    r"logs?[\s-]?out|signs?[\s-]?out|logout|mfa|2fa|multi[-\s]?factor|two[-\s]?factor|"
    r"one[-\s]?time\s+password|otp"
    r")\b",
    re.IGNORECASE,
)

_AUTH_RULES: tuple[BaselineRule, ...] = (
    BaselineRule(
        rule_key="auth.a1_valid_credentials",
        dimension="valid credential success",
        positive=re.compile(
            r"(?=[^\n]*\b(?:valid|success\w*|correct)\b)"
            r"(?=[^\n]*\b(?:credential\w*|password\w*|username|user\s?name|log[\s-]?in|"
            r"login|sign[\s-]?in|authentication)\b)",
            re.IGNORECASE,
        ),
        reason="no explicit successful sign-in evidence or product policy",
    ),
    BaselineRule(
        rule_key="auth.a2_invalid_username",
        dimension="invalid username",
        positive=re.compile(
            r"(?=[^\n]*\b(?:username|user\s?name)\b)"
            r"(?=[^\n]*\b(?:invalid|wrong|incorrect|unknown|rejected|not\s+found|"
            r"does\s+not\s+exist)\b)",
            re.IGNORECASE,
        ),
        related=_CREDENTIAL_INVALID,
        reason="no field-specific username evidence or explicit product policy",
    ),
    BaselineRule(
        rule_key="auth.a3_invalid_password",
        dimension="invalid password",
        positive=re.compile(
            r"(?=[^\n]*\b(?:password\w*|passcode)\b)"
            r"(?=[^\n]*\b(?:invalid|wrong|incorrect|unknown|rejected|not\s+found|"
            r"does\s+not\s+exist)\b)",
            re.IGNORECASE,
        ),
        related=_CREDENTIAL_INVALID,
        reason="no field-specific password evidence or explicit product policy",
    ),
    BaselineRule(
        rule_key="auth.a4_invalid_credentials",
        dimension="both credentials invalid",
        positive=re.compile(
            r"\b(?:invalid|wrong|incorrect)\s+credentials?\b"
            r"|\bcredentials?\s+(?:is\s+|are\s+)?(?:invalid|wrong|incorrect)\b"
            r"|(?=[^\n]*\b(?:username|user\s?name)\b)(?=[^\n]*\bpassword\b)"
            r"(?=[^\n]*\b(?:or|and)\b)(?=[^\n]*\b(?:invalid|wrong|incorrect|rejected)\b)",
            re.IGNORECASE,
        ),
        related=_CREDENTIAL_INVALID,
        reason="no generic invalid-credential evidence or explicit product policy",
    ),
    BaselineRule(
        rule_key="auth.a5_empty_username",
        dimension="empty username",
        positive=re.compile(
            r"(?=[^\n]*\b(?:username|user\s?name)\b)" + _FIELD_EMPTY,
            re.IGNORECASE,
        ),
        related=_CREDENTIAL_REQUIRED,
        reason="no mandatory or validation evidence for an empty username",
    ),
    BaselineRule(
        rule_key="auth.a6_empty_password",
        dimension="empty password",
        positive=re.compile(
            r"(?=[^\n]*\b(?:password\w*|passcode)\b)" + _FIELD_EMPTY,
            re.IGNORECASE,
        ),
        related=_CREDENTIAL_REQUIRED,
        reason="no mandatory or validation evidence for an empty password",
    ),
    BaselineRule(
        rule_key="auth.a7_empty_both_fields",
        dimension="both credential fields empty",
        positive=re.compile(
            r"(?=[^\n]*\b(?:username|user\s?name)\b)"
            r"(?=[^\n]*\bpassword\b)" + _FIELD_EMPTY,
            re.IGNORECASE,
        ),
        related=_CREDENTIAL_REQUIRED,
        reason="no mandatory or validation evidence covering both credential fields",
    ),
    BaselineRule(
        rule_key="auth.a8_boundary_input",
        dimension="credential input boundary",
        positive=re.compile(
            r"(?=[^\n]*\b(?:username|user\s?name|password\w*|passcode|credential\w*|pin)\b)"
            r"(?=[^\n]*\b(?:maximum|max|minimum|min|at\s+most|at\s+least|length|"
            r"characters?|limit\w*)\b)",
            re.IGNORECASE,
        ),
        reason="no boundary evidence for credential input",
    ),
    BaselineRule(
        rule_key="auth.a9_locked_account",
        dimension="locked account / failed-attempt behavior",
        positive=re.compile(
            r"(?=[^\n]*\b(?:(?:un)?lock\w*|block\w*|suspend\w*|throttl\w*|"
            r"failed\s+attempt\w*|attempt\s+(?:limit|count|threshold)|too\s+many)\b)"
            r"(?=[^\n]*\b(?:account\w*|login|log[\s-]?in|sign[\s-]?in|user|credential\w*|"
            r"password\w*|attempt\w*)\b)",
            re.IGNORECASE,
        ),
        negation=re.compile(
            r"(?=[^\n]*\b(?:lock\w*|block\w*|suspend\w*|attempt\w*)\b)"
            r"(?=[^\n]*\b(?:not|no|never|without|n't)\b)"
            r"(?=[^\n]*\b(?:configured|used|enabled|applied|implemented|supported|"
            r"required|exists)\b)",
            re.IGNORECASE,
        ),
        reason="no explicit account-lock or failed-attempt evidence or product policy",
    ),
    BaselineRule(
        rule_key="auth.a10_session_behavior",
        dimension="session behavior after login",
        positive=re.compile(_SESSION_BEHAVIOR, re.IGNORECASE),
        reason="no explicit session-behavior evidence or product policy",
    ),
    BaselineRule(
        rule_key="auth.a11_logout",
        dimension="logout / sign-out",
        positive=re.compile(
            r"(?=[^\n]*" + _LOGOUT + r")"
            r"(?=[^\n]*\b(?:end\w*|clear\w*|return\w*|redirect\w*|session|terminat\w*|"
            r"complet\w*|success\w*|displays?|confirms?|button|action|option|available|"
            r"provid\w*|visible)\b)",
            re.IGNORECASE,
        ),
        negation=re.compile(
            r"(?=[^\n]*" + _LOGOUT + r")"
            r"(?=[^\n]*\b(?:not|no|without)\b)"
            r"(?=[^\n]*\b(?:scope|excluded)\b)",
            re.IGNORECASE,
        ),
        scope=re.compile(_LOGOUT, re.IGNORECASE),
        related=re.compile(_LOGOUT, re.IGNORECASE),
        reason="logout is in scope but no explicit sign-out behavior evidence or product policy",
    ),
    BaselineRule(
        rule_key="auth.a12_mfa",
        dimension="MFA / second factor",
        positive=re.compile(
            r"\b(?:mfa|2fa|multi[-\s]?factor|two[-\s]?factor|second\s+factor|"
            r"one[-\s]?time\s+(?:password|code)|otp|verification\s+code)\b",
            re.IGNORECASE,
        ),
        negation=re.compile(
            r"(?=[^\n]*\b(?:mfa|2fa|multi[-\s]?factor|two[-\s]?factor|second\s+factor|"
            r"otp|one[-\s]?time)\b)"
            r"(?=[^\n]*\b(?:not|no|never|without|n't)\b)"
            r"(?=[^\n]*\b(?:required|used|enabled|supported|configured|implemented|"
            r"offered|present|needed)\b)",
            re.IGNORECASE,
        ),
        reason="no explicit MFA or second-factor evidence or product policy",
    ),
)

_AUTHORIZATION_RULES: tuple[BaselineRule, ...] = (
    BaselineRule(
        rule_key="authorization.authenticated_access",
        dimension="authenticated access gate",
        positive=re.compile(
            r"(?=[^\n]*\b(?:authenticated|authorized|authorization|unauthenticated|"
            r"admin\w*|role|permission\w*|guest)\b)"
            r"(?=[^\n]*\b(?:access\w*|authoriz\w*|allowed|denied|forbidden|visible|"
            r"accessible|permission|can\s+view|limit\w*)\b)",
            re.IGNORECASE,
        ),
        reason="no explicit authenticated-access evidence or product policy",
    ),
    BaselineRule(
        rule_key="authorization.unauthorized_handling",
        dimension="unauthorized / forbidden handling",
        positive=re.compile(
            r"\b(?:unauthoriz\w*|forbidden|unauthenticated|access\s+denied|"
            r"not\s+allowed|insufficient\s+permission\w*|403)\b",
            re.IGNORECASE,
        ),
        reason="no explicit unauthorized-access evidence or product policy",
    ),
    BaselineRule(
        rule_key="authorization.role_permissions",
        dimension="role / permission behavior",
        positive=re.compile(
            r"(?=[^\n]*\b(?:role|permission\w*|privileg\w*|admin\w*|rbac)\b)"
            r"(?=[^\n]*\b(?:only|allow\w*|deny\w*|denied|access\w*|view|edit|manage|"
            r"cannot|can\s+)\b)",
            re.IGNORECASE,
        ),
        reason="no explicit role or permission evidence or product policy",
    ),
)

_CRUD_RULES: tuple[BaselineRule, ...] = (
    BaselineRule(
        rule_key="crud.valid_input_accepted",
        dimension="valid input accepted",
        positive=re.compile(
            r"(?=[^\n]*\b(?:valid|correct|complete\w*|populated|success\w*|accepted|"
            r"sufficient)\b)"
            r"(?=[^\n]*\b(?:save\w*|submit\w*|store\w*|persist\w*|creat\w*|updat\w*|"
            r"add\w*|accept\w*|entr(?:y|ies)|record)\b)",
            re.IGNORECASE,
        ),
        reason="no explicit valid-input acceptance evidence or product policy",
    ),
    BaselineRule(
        rule_key="crud.invalid_input_prevented",
        dimension="invalid input prevented",
        positive=re.compile(
            r"(?=[^\n]*\b(?:mandatory|required|invalid|empty|blank|missing)\b)"
            r"(?=[^\n]*\b(?:reject\w*|prevent\w*|error|cannot|blocked|"
            r"must\s+be\s+provided|validation|not\s+be\s+saved|unable|mandatory|"
            r"required|empty|invalid)\b)",
            re.IGNORECASE,
        ),
        reason="no explicit invalid-input handling evidence or product policy",
    ),
    BaselineRule(
        rule_key="crud.record_persisted",
        dimension="record persisted after save",
        positive=re.compile(
            r"(?=[^\n]*\b(?:stored|saved|persist\w*|database|retained|written)\b)"
            r"(?=[^\n]*\b(?:record|entry|entries|data|row|value\w*|change\w*|input)\b)",
            re.IGNORECASE,
        ),
        reason="no explicit persistence evidence or product policy",
    ),
)

_SEARCH_RULES: tuple[BaselineRule, ...] = (
    BaselineRule(
        rule_key="search.criteria_applied",
        dimension="applied criterion produces described results",
        positive=re.compile(
            r"(?=[^\n]*\b(?:search|filter\w*|query|queries|criterion|criteria)\b)"
            r"(?=[^\n]*\b(?:result\w*|rows?|displayed|reflect\w*|follow\w*|returns?|"
            r"match\w*|filtered)\b)",
            re.IGNORECASE,
        ),
        reason="no explicit applied-criterion evidence or product policy",
    ),
    BaselineRule(
        rule_key="search.no_results_state",
        dimension="no-results / empty state",
        positive=re.compile(
            r"\b(?:no\s+(?:matching\s+)?results?\b|no\s+matching\b|"
            r"empty\s+(?:result|state)|nothing\s+(?:is\s+)?displayed|does\s+not\s+match)",
            re.IGNORECASE,
        ),
        reason="no explicit no-results evidence or product policy",
    ),
    BaselineRule(
        rule_key="search.clear_reset",
        dimension="search clear / reset behavior",
        positive=re.compile(
            r"(?=[^\n]*\b(?:clear\w*|reset\w*)\b)"
            r"(?=[^\n]*\b(?:search|filter\w*|query|criterion|criteria|entered|input)\b)",
            re.IGNORECASE,
        ),
        reason="no explicit search reset evidence or product policy",
    ),
)

_FILE_UPLOAD_RULES: tuple[BaselineRule, ...] = (
    BaselineRule(
        rule_key="file_upload.accepted_types",
        dimension="accepted file types",
        positive=re.compile(
            r"(?=[^\n]*\b(?:pdf|xlsx|docx|csv|file\w*|document\w*|type\w*|format\w*)\b)"
            r"(?=[^\n]*\b(?:only|restrict\w*|limit\w*|accept\w*|allow\w*|support\w*|"
            r"require\w*|include\w*)\b)",
            re.IGNORECASE,
        ),
        evidence_kinds=("file_boundary",),
        reason="no explicit accepted-file-type evidence or product policy",
    ),
    BaselineRule(
        rule_key="file_upload.rejected_types",
        dimension="unsupported file types rejected",
        positive=re.compile(
            r"(?=[^\n]*\b(?:pdf|file\w*|document\w*|type\w*|format\w*)\b)"
            r"(?=[^\n]*\b(?:reject\w*|unsupported|invalid|not\s+allowed|prevent\w*|"
            r"block\w*|non-pdf|unable)\b)",
            re.IGNORECASE,
        ),
        reason="no explicit unsupported-type evidence or product policy",
    ),
    BaselineRule(
        rule_key="file_upload.size_limits",
        dimension="upload size limit",
        positive=re.compile(
            r"(?=[^\n]*(?:\b\d+\s*(?:mb|kb|gb|bytes?)\b|"
            r"\b(?:size|length|upload|attachment|file)\b))"
            r"(?=[^\n]*\b(?:maximum|max|minimum|min|limit\w*|at\s+most|at\s+least|\d+)\b)",
            re.IGNORECASE,
        ),
        reason="no explicit upload size evidence or product policy",
    ),
)

_API_RULES: tuple[BaselineRule, ...] = (
    BaselineRule(
        rule_key="api.success_response",
        dimension="success response",
        positive=re.compile(
            r"(?=[^\n]*\b(?:2\d\d|success\w*|ok\b|created|accepted|healthy)\b)"
            r"(?=[^\n]*\b(?:response|status|return\w*|payload|body|endpoint|api|"
            r"request)\b)",
            re.IGNORECASE,
        ),
        reason="no explicit success-response evidence or product policy",
    ),
    BaselineRule(
        rule_key="api.error_response",
        dimension="error response",
        positive=re.compile(
            r"(?=[^\n]*\b(?:[45]\d\d|error|failed|failure|reject\w*|invalid)\b)"
            r"(?=[^\n]*\b(?:response|status|code|endpoint|api|payload|body)\b)",
            re.IGNORECASE,
        ),
        reason="no explicit error-response evidence or product policy",
    ),
    BaselineRule(
        rule_key="api.request_validation",
        dimension="request validation",
        positive=re.compile(
            r"(?=[^\n]*\b(?:missing|required|invalid|malformed|empty)\b)"
            r"(?=[^\n]*\b(?:request|payload|body|parameter|field|json|attribute)\b)",
            re.IGNORECASE,
        ),
        reason="no explicit request-validation evidence or product policy",
    ),
)

_ERROR_RULES: tuple[BaselineRule, ...] = (
    BaselineRule(
        rule_key="error.failure_communication",
        dimension="failure state communicated",
        positive=re.compile(
            r"(?=[^\n]*\b(?:error\w*|fail\w*|failure|unsuccess\w*|invalid\w*|exception)\b)"
            r"(?=[^\n]*\b(?:display\w*|show\w*|message|dialog|notification|toast|state|"
            r"feedback)\b)",
            re.IGNORECASE,
        ),
        reason="no explicit failure-communication evidence or product policy",
    ),
    BaselineRule(
        rule_key="error.retry_path",
        dimension="retry path",
        positive=re.compile(
            r"\b(?:retry|try\s+again|recalculate|attempt\s+again)\b",
            re.IGNORECASE,
        ),
        reason="no explicit retry-path evidence or product policy",
    ),
    BaselineRule(
        rule_key="error.validation_feedback",
        dimension="validation feedback",
        positive=re.compile(
            r"(?=[^\n]*\b(?:validation|validate|invalid|required|mandatory)\b)"
            r"(?=[^\n]*\b(?:message|inline|field|input|highlight\w*|indicator|error)\b)",
            re.IGNORECASE,
        ),
        reason="no explicit validation-feedback evidence or product policy",
    ),
)

_STATE_SESSION_RULES: tuple[BaselineRule, ...] = (
    BaselineRule(
        rule_key="state.explicit_states_displayed",
        dimension="explicitly defined states",
        positive=re.compile(
            r"\b(?:values?\s+include|states?\s+include|statuses?\s+include|"
            r"lifecycle|status\s+values?)\b",
            re.IGNORECASE,
        ),
        evidence_kinds=("state",),
        reason="no explicit state evidence or product policy",
    ),
    BaselineRule(
        rule_key="state.transitions",
        dimension="state transitions",
        positive=re.compile(
            r"\b(?:transition\w*|move\s+from|allowed\s+(?:next|transition)|"
            r"next\s+state|from\s+\w+\s+to\s+\w+)\b",
            re.IGNORECASE,
        ),
        reason="no explicit state-transition evidence or product policy",
    ),
    BaselineRule(
        rule_key="session.behavior",
        dimension="session behavior",
        positive=re.compile(_SESSION_BEHAVIOR, re.IGNORECASE),
        scope_exclusion=AUTH_DOMAIN,
        reason="no explicit session-behavior evidence or product policy",
    ),
)

_CONFIRMATION_RULES: tuple[BaselineRule, ...] = (
    BaselineRule(
        rule_key="confirmation.confirm_path",
        dimension="confirm path",
        positive=re.compile(
            r"(?=[^\n]*\bconfirm\w*\b)"
            r"(?=[^\n]*\b(?:action\w*|proceed\w*|complete\w*|save\w*|yes|button|dialog|"
            r"path)\b)",
            re.IGNORECASE,
        ),
        reason="no explicit confirm-path evidence or product policy",
    ),
    BaselineRule(
        rule_key="confirmation.cancel_path",
        dimension="cancel path",
        positive=re.compile(
            r"(?=[^\n]*\bcancel\w*\b)"
            r"(?=[^\n]*\b(?:action\w*|keeps?|return\w*|discard\w*|button|dialog|path|"
            r"abort\w*|back)\b)",
            re.IGNORECASE,
        ),
        reason="no explicit cancel-path evidence or product policy",
    ),
    BaselineRule(
        rule_key="confirmation.destructive_outcome",
        dimension="destructive action outcome",
        positive=re.compile(
            r"(?=[^\n]*\b(?:delete\w*|remove\w*|discard\w*|destructive|permanent\w*)\b)"
            r"(?=[^\n]*\b(?:confirm\w*|permanent\w*|deleted|removed|restor\w*|undo|"
            r"cannot|irreversible|warning)\b)",
            re.IGNORECASE,
        ),
        reason="no explicit destructive-outcome evidence or product policy",
    ),
)

_NAVIGATION_RULES: tuple[BaselineRule, ...] = (
    BaselineRule(
        rule_key="navigation.items_available",
        dimension="navigation items available",
        positive=re.compile(
            r"(?=[^\n]*\b(?:tab|tabs|navigation|menu)\w*)"
            r"(?=[^\n]*\b(?:provid\w*|display\w*|available|label\w*|title|item\w*|"
            r"entry|entries)\b)",
            re.IGNORECASE,
        ),
        evidence_kinds=("presence",),
        reason="no explicit navigation-item evidence or product policy",
    ),
    BaselineRule(
        rule_key="navigation.active_tab_state",
        dimension="active tab indication",
        positive=re.compile(
            r"(?=[^\n]*\b(?:active|selected|current|highlighted|default)\b)"
            r"(?=[^\n]*\btab\b)",
            re.IGNORECASE,
        ),
        reason="no explicit active-tab evidence or product policy",
    ),
)


# Fixed, ordered rule storage: iteration order determines UBI order, so it
# must never come from a dict or set.
BASELINE_DOMAINS: tuple[BaselineDomain, ...] = (
    BaselineDomain("authentication", AUTH_DOMAIN, _AUTH_RULES),
    BaselineDomain(
        "authorization",
        re.compile(
            r"\b(?:access\s+control|permission\w*|role|authoriz\w*|unauthoriz\w*|"
            r"forbidden|privileg\w*|authenticated\s+users?|only\s+(?:the\s+)?"
            r"(?:admin|authenticated|authorized)\w*|can\s+access)\b",
            re.IGNORECASE,
        ),
        _AUTHORIZATION_RULES,
    ),
    BaselineDomain(
        "crud",
        re.compile(
            r"\b(?:form|save|submit\w*|entr(?:y|ies)|create\w*|update\w*|edit\w*|"
            r"add\s+new|data\s+entry|record)\b",
            re.IGNORECASE,
        ),
        _CRUD_RULES,
    ),
    BaselineDomain(
        "search",
        re.compile(r"\b(?:search|filter\w*|query|queries|look\s?up)\b", re.IGNORECASE),
        _SEARCH_RULES,
    ),
    BaselineDomain(
        "file_upload",
        re.compile(
            r"\b(?:upload\w*|attachment\w*|file\s+type|document\s+type|"
            r"\.pdf|\.xlsx|\.docx|\.csv|import\s+file|pdf)\b",
            re.IGNORECASE,
        ),
        _FILE_UPLOAD_RULES,
    ),
    BaselineDomain(
        "api",
        re.compile(
            r"\b(?:api|endpoint\w*|http|rest(?:ful)?|json|status\s+code|payload|"
            r"request\s+body|response\s+body)\b",
            re.IGNORECASE,
        ),
        _API_RULES,
    ),
    BaselineDomain(
        "error",
        re.compile(
            r"\b(?:error\w*|fail\w*|invalid\w*|validation|validate\w*|unsuccess\w*|"
            r"incorrect|exception)\b",
            re.IGNORECASE,
        ),
        _ERROR_RULES,
    ),
    BaselineDomain(
        "state_session",
        re.compile(
            r"\b(?:status|state\w*|lifecycle|session|signed\s+in|workflow)\b",
            re.IGNORECASE,
        ),
        _STATE_SESSION_RULES,
    ),
    BaselineDomain(
        "confirmation",
        re.compile(
            r"\b(?:confirm\w*|cancel\w*|are\s+you\s+sure|discard\w*|destructive|"
            r"delete\w*|remove\w*|permanent\w*)\b",
            re.IGNORECASE,
        ),
        _CONFIRMATION_RULES,
    ),
    BaselineDomain(
        "navigation",
        re.compile(
            r"\b(?:tab|tabs|navigation|navigate|menu|breadcrumb|sidebar|toolbar)\b",
            re.IGNORECASE,
        ),
        _NAVIGATION_RULES,
    ),
)

_GUARDRAIL = re.compile(
    r"^(?:do not|don't|must not|the generator|if implementation|the exact eligibility|"
    r"treat this as|treat these as)\b"
    r"|\b(?:not\s+(?:fully|completely|sufficiently)\s+defined|"
    r"not\s+available\s+in\s+(?:the\s+)?supplied\s+evidence|"
    r"not\s+sufficiently\s+supported|must\s+not\s+be\s+invented|do\s+not\s+infer)\b",
    re.IGNORECASE,
)


def evaluate_baseline(
    requirement: Requirement,
    evidence_atoms: list[EvidenceAtom],
    subject: str,
) -> BaselineEvaluation:
    """Evaluate every applicable baseline dimension for one requirement.

    Returns materialized dimensions, not-applicable dimensions, retained UBIs
    for applicable-but-unsupported dimensions, and any policy candidates that
    still need a scenario of their own.
    """

    evaluation = BaselineEvaluation()
    if requirement.status != "TESTABLE":
        return evaluation

    text = _full_text(requirement)
    atoms = [atom for atom in evidence_atoms if atom.kind != "guardrail"]
    atom_texts = {_normalize(atom.text) for atom in atoms}
    policy_lines = [
        cleaned
        for values in (requirement.constraints, requirement.numeric_limits)
        for cleaned in (_clean_line(value) for value in values)
        if cleaned and not _GUARDRAIL.search(cleaned)
    ]

    for domain in BASELINE_DOMAINS:
        if not domain.applicability.search(text):
            continue
        for rule in domain.rules:
            if rule.scope is not None and not rule.scope.search(text):
                evaluation.not_applicable.append(rule.rule_key)
                continue
            if rule.scope_exclusion is not None and rule.scope_exclusion.search(text):
                evaluation.not_applicable.append(rule.rule_key)
                continue

            evidence_positive = any(
                _matches(rule, atom) and not _negated(rule, atom.text)
                for atom in atoms
            )
            positive_policy_lines = [
                line
                for line in policy_lines
                if rule.positive.search(line) and not _negated(rule, line)
            ]
            negated = any(_negated(rule, atom.text) for atom in atoms) or any(
                _negated(rule, line) for line in policy_lines
            )

            if evidence_positive:
                evaluation.materialized.append((rule.rule_key, _EVIDENCE_SOURCE))
                continue
            if positive_policy_lines:
                evaluation.materialized.append((rule.rule_key, _POLICY_SOURCE))
                for line in positive_policy_lines:
                    if _normalize(line) in atom_texts:
                        continue
                    evaluation.policy_candidates.append(
                        (
                            "positive",
                            "EP",
                            f"Verify the explicit product policy for {subject}: {line}.",
                            "high",
                        )
                    )
                continue
            if negated:
                evaluation.not_applicable.append(rule.rule_key)
                continue

            related_pattern = rule.related or rule.positive
            evaluation.unresolved.append(
                UnresolvedBaselineItem(
                    requirement_ref=requirement.id,
                    rule_key=rule.rule_key,
                    dimension=rule.dimension,
                    status=STATUS_APPLICABLE_UNRESOLVED,
                    disposition=DISPOSITION_RETAINED,
                    reason=rule.reason,
                    evidence_refs=tuple(
                        atom.id for atom in atoms if related_pattern.search(atom.text)
                    ),
                    requires_policy=rule.requires_policy,
                )
            )
    return evaluation


def _matches(rule: BaselineRule, atom: EvidenceAtom) -> bool:
    if atom.kind in rule.evidence_kinds:
        return True
    return bool(rule.positive.search(atom.text))


def _negated(rule: BaselineRule, line: str) -> bool:
    return rule.negation is not None and bool(rule.negation.search(line))


def _full_text(requirement: Requirement) -> str:
    lines = [
        requirement.title,
        requirement.statement,
        *requirement.details,
        *requirement.acceptance_criteria,
        *requirement.constraints,
        *requirement.numeric_limits,
        *requirement.tags,
    ]
    return "\n".join(line.strip() for line in lines if line and line.strip())


def _clean_line(value: str) -> str:
    cleaned = re.sub(r"^\s*[-*+•]\s*", "", value or "")
    return re.sub(r"\s+", " ", cleaned.strip().strip("`")).strip()


def _normalize(value: str) -> str:
    normalized = re.sub(r"[^\w]+", " ", value.lower(), flags=re.UNICODE)
    return re.sub(r"\s+", " ", normalized).strip()
