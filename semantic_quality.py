"""Deterministic semantic-quality gate for generated test-case content.

Enforces Quality Contract v1: requirement-local evidence binding, executable
steps, observable and determinate expected results, literal preservation, and
no internal guardrail/meta language in tester-facing fields.

The gate is scope-relative: every claim is checked against the scenario's
authorized evidence scope, never against a bare lexical blacklist.
"""

from __future__ import annotations

from dataclasses import dataclass
import difflib
import re

from models.coverage_model import EvidenceAtom, ScenarioIntent


# ---------------------------------------------------------------------------
# Internal meta / guardrail language (Rule H). These are generation/audit
# concerns and must never appear in tester-facing fields.
# ---------------------------------------------------------------------------

META_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "not-assumed disclaimer",
        re.compile(
            r"tidak\s+diasumsikan|\b(?:is|are)\s+not\s+assumed\b|"
            r"without\s+assuming|\bnot\s+assumed\b",
            re.IGNORECASE,
        ),
    ),
    (
        "unspecified-semantics disclaimer",
        re.compile(
            r"unspecified\s+semantics|semantik\s+yang\s+tidak\s+dinyatakan|"
            r"semantics\s+not\s+(?:stated|declared)",
            re.IGNORECASE,
        ),
    ),
    (
        "as-stated disclaimer",
        re.compile(
            r"sesuai\s+yang\s+dinyatakan|sebagaimana\s+dinyatakan|"
            r"perilaku\s+yang\s+dinyatakan|hasil\s+sesuai\s+(?:yang\s+)?dinyatakan|"
            r"\bas\s+stated\b|\bas\s+declared\b|\bas\s+described\b",
            re.IGNORECASE,
        ),
    ),
    (
        "described-behavior reference",
        re.compile(
            r"perilaku\s+yang\s+di(?:jelaskan|uraikan)|yang\s+dijelaskan|"
            r"\bdescribed\s+(?:security\s+)?behavio(?:u)?r\b|"
            r"\bbehavio(?:u)?r\s+(?:that\s+is\s+)?described\b|"
            r"\bbehavior\s+described\b|\bbehaviour\s+described\b",
            re.IGNORECASE,
        ),
    ),
    (
        "explicitly-described reference",
        re.compile(
            r"explicitly\s+described|secara\s+eksplisit\s+di(?:jelaskan|uraikan)",
            re.IGNORECASE,
        ),
    ),
    (
        "as-needed disclaimer",
        re.compile(
            r"sesuai\s+kebutuhan|\bas\s+needed\b|\bas\s+appropriate\b|seperlunya",
            re.IGNORECASE,
        ),
    ),
    (
        "generic security behavior",
        re.compile(
            r"perilaku\s+keamanan|\bsecurity\s+behavio(?:u)?r\b|"
            r"\baspek\s+keamanan\b|\bsecurity\s+aspects?\b",
            re.IGNORECASE,
        ),
    ),
    (
        "generic consistency claim",
        re.compile(
            r"amati\s+konsistensi|observe\s+(?:the\s+)?consistenc|"
            r"tetap\s+konsisten|remains?\s+consistent|\bconsistent\s+with\s+the\s+system|"
            r"konsistensi\s+sistem",
            re.IGNORECASE,
        ),
    ),
    (
        "behavior-fulfilled claim",
        re.compile(
            r"perilaku\s+(?:terpenuhi|dipenuhi)|"
            r"\bbehavio(?:u)?r\s+is\s+(?:satisfied|fulfilled|met)\b|"
            r"\bbehavio(?:u)?r\s+(?:satisfied|fulfilled)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "stated-result claim",
        re.compile(
            r"\bresults?\s+as\s+(?:stated|declared|documented)\b|"
            r"\boutcome\s+as\s+(?:stated|declared)\b|"
            r"sesuai\s+(?:yang\s+)?dinyatakan",
            re.IGNORECASE,
        ),
    ),
    (
        "self-correction draft",
        re.compile(
            r"lebih\s+tepatnya|\bmore\s+precisely\b|\brather:\s*",
            re.IGNORECASE,
        ),
    ),
    (
        "other-behavior disclaimer",
        re.compile(
            r"perilaku\s+lain|\bother\s+(?:unstated\s+)?behavio(?:u)?r\s+(?:is\s+)?not\b|"
            r"\bno\s+other\s+(?:unstated\s+)?behavio(?:u)?r\b",
            re.IGNORECASE,
        ),
    ),
)


# ---------------------------------------------------------------------------
# Executable steps (Rule D): an action opener plus a concrete target.
# ---------------------------------------------------------------------------

_STEP_OPENER = re.compile(
    r"^(?:\d+[\.\)]\s*|[-*•]\s*)*(?:please\s+)?"
    r"(?:open|navigate|go\s+to|select|choose|click|press|enter|type|input|fill|"
    r"clear|submit|save|observe|view|verify|check|confirm|review|attempt|try|"
    r"leave|set|add|remove|delete|create|upload|download|log\s*(?:in|out)|"
    r"sign\s*(?:in|out)|scroll|hover|drag|double[\s-]click|reload|refresh|run|"
    r"trigger|restore|close|access|inspect|compare|wait|locate|find|identify|"
    r"search\s+for|"
    r"buka|akses|navigasi|pilih|klik|tekan|masukkan|isi|ketik|kirim|simpan|"
    r"amati|lihat|periksa|verifikasi|konfirmasi|tinjau|coba|kosongkan|hapus|"
    r"tambah|buat|unggah|unduh|masuk|keluar|gulir|muat\s+ulang|jalankan|"
    r"biarkan|tinggalkan|tutup|perhatikan|bandingkan|tunggu|lacak|temukan|"
    r"cari|kenali)\b",
    re.IGNORECASE,
)

_STEP_ANCHOR = re.compile(
    r"[\"'“”‘’]|"
    r"\b(?:tombol|button|halaman|page|screen|layar|form|menu|tabs?|dialog|"
    r"pesan|message|label|teks|text|tabel|table|rows?|baris|columns?|kolom|"
    r"icons?|ikon|dropdown|checkbox|radio|lists?|detail|username|user\s+name|"
    r"password|passcode|email|kata\s+sandi|\bsandi\b|nilai|value|data|file|"
    r"gambar|image|nama|name|nomor|number|period|tanggal|date|cari|search|"
    r"filter|login|log-in|logout|dashboard|sessions?|sesi|tokens?|result|hasil|"
    r"credential|kredensials?|fields?|account|akun|status|states?|options?|"
    r"opsi|pilihan|record|browser|urls?|endpoints?|api|requests?|respons(?:e|es)|"
    r"headers?|quer(?:y|ies)|database|cancel|batal|submit|save|simpan|start|"
    r"mulai|stops?|berhenti|characters?|karakter|digits?|angka|limit|batas|"
    r"total|count|jumlah|date|period|flags?|toggle|switch|sakelar)\b",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Observable expected results (Rule E) and determinate outcomes (Rule F).
# ---------------------------------------------------------------------------

_OBSERVABLE = re.compile(
    r"ditampilkan|menampilkan|tampil|muncul|terlihat|tersembunyi|"
    r"disembunyikan|sembunyi|diterima|ditolak|dicegah|diizinkan|dibenarkan|"
    r"tersedia|tidak\s+tersedia|dikirim|dikirimkan|disimpan|dibuat|dihapus|"
    r"diubah|dipilih|dimasukkan|dikosongkan|diperbarui|ditambahkan|"
    r"berhasil|gagal|pesan|error|galat|"
    r"displayed|display|shown|show|appears?|appear|visible|hidden|masked|"
    r"accepted|rejected|prevented|allowed|denied|available|unavailable|"
    r"saved|stored|created|removed|updated|selected|submitted|redirected|"
    r"navigated|remains?|stays?|logged\s+in|message|error|success|fail(?:ed|ure)?|"
    r"match(?:es|ed)?|differs?|changed|unchanged|open(?:ed)?|closed|"
    r"contains?|includes?|equals?|count|jumlah|total|nilai|value|return\w*",
    re.IGNORECASE,
)

_HEDGE = re.compile(r"\batau\b|\band\s*/\s*or\b|\bdan\s*/\s*atau\b|\bor\b", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Scope-relative claim families (Rules A/B/C/I). A family claim in content is
# allowed only when the scenario's authorized scope states the same family.
# These families are sentence-insensitive by design: their shapes are
# self-contained policy assertions.
# ---------------------------------------------------------------------------

CLAIM_FAMILIES: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "session expiry/timeout",
        re.compile(
            r"(?:session|sesi).{0,40}(?:expir|timeout|time[\s-]out|idle|"
            r"kadaluarsa|berakhir|hangus)"
            r"|(?:expir|timeout|time[\s-]out|kadaluarsa|berakhir).{0,40}"
            r"(?:session|sesi)",
            re.IGNORECASE | re.DOTALL,
        ),
    ),
    (
        "lockout/rate-limit threshold",
        re.compile(
            r"(?:lock\w*|blokir|blokir).{0,40}(?:after|setelah|within|dalam|"
            r"attempt|percobaan)"
            r"|\d+\s*(?:attempts?|percobaan|minutes?|menit|seconds?|detik|"
            r"hours?|jam|days?|hari)\b"
            r"|rate[\s-]limit\w*",
            re.IGNORECASE | re.DOTALL,
        ),
    ),
    (
        "MFA challenge",
        re.compile(
            r"(?:mfa|2fa|\botp\b|multi[\s-]factor|two[\s-]factor|second[\s-]factor).{0,50}"
            r"(?:prompt|request|challenge|verif|kode|code|required|diminta|"
            r"displayed|shown|entered|dimasukkan)",
            re.IGNORECASE | re.DOTALL,
        ),
    ),
    (
        "HTTP status code",
        re.compile(r"\b[45]\d{2}\b"),
    ),
    (
        "authentication bypass",
        re.compile(
            r"bypass\w*|authentication\s+evasion|melewati\s+autentikasi|"
            r"brute\s+force|credential\s+stuffing|session\s+hijack\w*|"
            r"pembajakan\s+sesi",
            re.IGNORECASE,
        ),
    ),
)


# ---------------------------------------------------------------------------
# Field-local claim families (L3 hardening H1/H2). These constructs must be
# self-contained within one field (title, precondition, step, or expected
# result) so unrelated proximity across a Step/Expected boundary can never
# fabricate a claim. Detection is semantic: narrow masking constructs and
# policy-shaped numeric claims, never "any number near a keyword".
# ---------------------------------------------------------------------------

_PASSWORDISH = r"(?:password|passcode|kata\s+sandi|\bsandi\b)"

_MASKING_CONSTRUCT = (
    r"(?:(?:plain\s*text|plaintext|clear\s*text|teks\s+biasa)"
    r"|(?:(?:is|are|was|were)?\s*not\s+(?:shown|displayed|visible|"
    r"ditampilkan|terlihat))"
    r"|mask(?:ed|ing)"
    r"|(?:hidden|obscured|concealed|disembunyikan|tersembunyi|tertutupi)"
    r"|(?:revealed|exposed|terekspos)"
    r"|in\s+clear(?:\s+text)?|secara\s+terbuka)"
)

_MASKING_PATTERN = re.compile(
    rf"{_PASSWORDISH}.{{0,40}}{_MASKING_CONSTRUCT}"
    rf"|(?:{_MASKING_CONSTRUCT}).{{0,40}}{_PASSWORDISH}",
    re.IGNORECASE | re.DOTALL,
)

_PASSWORD_POLICY_COUNT = (
    r"\d+\s*(?:characters?|letters?|digits?|symbols?|karakter|huruf|angka|simbol)"
)
_PASSWORD_POLICY_CLASS = (
    r"(?:uppercase|lowercase|capital\s+letter|special\s+character|alphanumeric|"
    r"digit\w*|numerical|complex\w*|huruf\s+(?:besar|kecil)|karakter\s+khusus|angka)"
)
_PASSWORD_POLICY_MODAL = r"(?:must|shall|requir\w+|harus|wajib|diwajibkan)"

_PASSWORD_POLICY_PATTERN = re.compile(
    rf"{_PASSWORDISH}.{{0,50}}"
    rf"(?:{_PASSWORD_POLICY_COUNT}|{_PASSWORD_POLICY_MODAL}.{{0,60}}{_PASSWORD_POLICY_CLASS})"
    rf"|(?:{_PASSWORD_POLICY_COUNT}|{_PASSWORD_POLICY_CLASS}.{{0,60}}{_PASSWORD_POLICY_MODAL})"
    rf".{{0,50}}{_PASSWORDISH}",
    re.IGNORECASE | re.DOTALL,
)

_RETRY_POLICY_PATTERN = re.compile(
    r"(?:retr\w+|tries|try\s+again|mencoba\s+lagi|mengulang\w*|percobaan\s+ulang)\b"
    r".{0,30}(?:\d+\s*(?:times?|kali)|twice|thrice)"
    r"|(?:\d+\s*(?:times?|kali)|twice|thrice)\b.{0,30}"
    r"(?:retr\w+|attempt\w*|tries|try\s+again)",
    re.IGNORECASE | re.DOTALL,
)

_TIMEOUT_POLICY_PATTERN = re.compile(
    r"(?:time[\s-]?outs?|times?\s+out|timeout\w*|expir\w*|kadaluarsa|berakhir|"
    r"hangus|idle[\s-]?timeout)"
    r".{0,40}"
    r"\d+\s*(?:s\b|sec(?:ond)?s?\b|minutes?|mins?|hours?|days?|menit|detik|jam|hari)"
    r"|\d+\s*(?:s\b|sec(?:ond)?s?\b|minutes?|mins?|hours?|days?|menit|detik|jam|hari)"
    r".{0,40}"
    r"(?:time[\s-]?outs?|times?\s+out|timeout\w*|expir\w*|kadaluarsa|berakhir|"
    r"hangus|idle[\s-]?timeout)",
    re.IGNORECASE | re.DOTALL,
)

FIELD_LOCAL_FAMILIES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("password masking/visibility", _MASKING_PATTERN),
    ("password complexity/length", _PASSWORD_POLICY_PATTERN),
    ("retry count policy", _RETRY_POLICY_PATTERN),
    ("timeout/expiry policy", _TIMEOUT_POLICY_PATTERN),
)


# ---------------------------------------------------------------------------
# Controlled entity vocabulary for cross-requirement leakage (Rule B).
# A content claim about an entity absent from the scenario's authorized scope
# is either leakage from another requirement or an invented product fact.
# ---------------------------------------------------------------------------

ENTITIES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("password", re.compile(r"password|kata\s+sandi|\bsandi\b|passcode", re.IGNORECASE)),
    ("username", re.compile(r"user\s?name|nama\s+pengguna", re.IGNORECASE)),
    ("session", re.compile(r"\bsessions?\b|\bsesi\b", re.IGNORECASE)),
    ("token", re.compile(r"\btokens?\b", re.IGNORECASE)),
    ("cookie", re.compile(r"\bcookies?\b|\bkuki\b", re.IGNORECASE)),
    ("MFA/OTP", re.compile(r"\bmfa\b|\b2fa\b|\botp\b|multi[\s-]factor|two[\s-]factor|dua\s+faktor", re.IGNORECASE)),
    ("role", re.compile(r"\broles?\b|\bperan\b", re.IGNORECASE)),
    ("permission", re.compile(r"\bpermissions?\b|hak\s+akses|\bizin\b", re.IGNORECASE)),
    ("dashboard", re.compile(r"\bdashboard\b", re.IGNORECASE)),
    ("logout", re.compile(
        r"logouts?|log[\s-]out|logged[\s-]out|logging[\s-]out|keluar\s+dari",
        re.IGNORECASE,
    )),
    ("encryption", re.compile(r"encrypt\w*|enkripsi|decrypt\w*|dekripsi", re.IGNORECASE)),
    ("rate limiting", re.compile(r"rate[\s-]limit\w*|brute\s+force", re.IGNORECASE)),
)


# ---------------------------------------------------------------------------
# Security must be evidence-bound (Rule J).
# ---------------------------------------------------------------------------

_SECURITY_PREDICATE = re.compile(
    r"plain\s*text|plaintext|teks\s+biasa|mask\w*|disembunyikan|tersembunyi|"
    r"injection|xss|sql\s*injection|csrf|xsrf|"
    r"unauthoriz\w*|unauthorised|forbidden|tidak\s+sah|hak\s+akses|"
    r"brute\s+force|credential\s+stuffing|bypass\w*|escalation|replay|forgery|"
    r"(?:invalid|wrong|incorrect)\s+(?:user\s?name|password|passcode|credential\w*)|"
    r"credential\w*\s+(?:fail\w*|error|reject\w*|denied|invalid)|"
    r"encrypt\w*|enkripsi|decrypt\w*|hash\w*|certificate|sertifikat|https|"
    r"escap\w*|traversal|locked\s+account|akun\s+terkunci|"
    r"tidak\s+(?:ditampilkan|terlihat|diterima)|ditolak\s+karena",
    re.IGNORECASE,
)


_LITERAL_QUOTE_DOUBLE = re.compile(r"\"([^\"\n]{3,})\"")
_LITERAL_QUOTE_SINGLE = re.compile(r"'([^'\n]{3,})'")
_SAMPLE_VALUE = re.compile(r"sample value\s+'([^']+)'", re.IGNORECASE)

_MAX_MASKABLE_TEXT = 90
_CORRUPTION_RATIO = 0.75


@dataclass(frozen=True)
class ScenarioAuthority:
    """The evidence scope authorized for one planned scenario."""

    scenario: ScenarioIntent
    support_texts: tuple[str, ...]
    own_texts: tuple[str, ...]
    foreign_texts: tuple[str, ...]

    @property
    def support(self) -> str:
        return " ".join(self.support_texts)

    @property
    def own(self) -> str:
        return " ".join(self.own_texts)


def authorized_evidence_texts(
    scenario: ScenarioIntent,
    evidence_atoms: list[EvidenceAtom],
) -> tuple[str, ...]:
    """Return the authorized evidence texts for one scenario.

    Scenario-bound atoms take precedence (Rule C). When the scenario binds no
    atoms, the requirement-local atoms are the fallback scope (Rule A).
    """

    by_id = {atom.id: atom for atom in evidence_atoms}
    bound = tuple(
        by_id[ref].text for ref in scenario.evidence_refs if ref in by_id
    )
    if bound:
        return bound
    return tuple(
        atom.text for atom in evidence_atoms
        if atom.requirement_ref == scenario.requirement_ref
    )


def build_authorities(
    scenarios: list[ScenarioIntent],
    evidence_atoms: list[EvidenceAtom] | None,
) -> dict[str, ScenarioAuthority]:
    """Build the evidence authority for every scenario in one batch."""

    atoms = list(evidence_atoms or ())
    authorities: dict[str, ScenarioAuthority] = {}
    for scenario in scenarios:
        support = tuple(
            [scenario.intent, *authorized_evidence_texts(scenario, atoms)]
        )
        own = tuple(
            [scenario.intent, *(
                atom.text for atom in atoms
                if atom.requirement_ref == scenario.requirement_ref
            )]
        )
        foreign = tuple(
            atom.text for atom in atoms
            if atom.requirement_ref != scenario.requirement_ref
        )
        authorities[scenario.id] = ScenarioAuthority(
            scenario=scenario,
            support_texts=support,
            own_texts=own,
            foreign_texts=foreign,
        )
    return authorities


def validate_content(
    *,
    title: str,
    preconditions: list[str],
    steps: list[str],
    expected_result: str,
    authority: ScenarioAuthority,
) -> str | None:
    """Return a contract violation reason, or None when the content passes."""

    fields: tuple[tuple[str, str], ...] = (
        ("title", title),
        ("preconditions", " ".join(preconditions)),
        ("steps", " ".join(steps)),
        ("expected_result", expected_result),
    )

    for field_name, text in fields:
        for label, pattern in META_PATTERNS:
            if pattern.search(text):
                return (
                    f"{field_name} contains internal/meta wording "
                    f"({label}); guardrail language must not reach testers"
                )

    for position, step in enumerate(steps, start=1):
        stripped = step.strip()
        if not _STEP_OPENER.match(stripped):
            return (
                f"step {position} is not a concrete test action "
                f"(no accepted action verb): {step!r}"
            )
        if not _STEP_ANCHOR.search(stripped):
            return (
                f"step {position} lacks a concrete target "
                f"(button, field, page, message, value, ...): {step!r}"
            )

    if not _OBSERVABLE.search(expected_result) and not _LITERAL_QUOTE_DOUBLE.search(expected_result):
        return "expected_result does not state an observable outcome"

    content_all = " ".join([title, " ".join(preconditions), " ".join(steps), expected_result])

    for label, pattern in CLAIM_FAMILIES:
        if pattern.search(content_all) and not pattern.search(authority.support):
            return (
                f"unsupported claim family '{label}' in content; the scenario's "
                "authorized evidence does not state it"
            )

    field_texts = (title, *preconditions, *steps, expected_result)
    for field_text in field_texts:
        for label, pattern in FIELD_LOCAL_FAMILIES:
            if pattern.search(field_text) and not pattern.search(authority.support):
                return (
                    f"unsupported claim family '{label}' in content; the scenario's "
                    "authorized evidence does not state it"
                )

    for entity, pattern in ENTITIES:
        if pattern.search(content_all) and not pattern.search(authority.support):
            return (
                f"claim about '{entity}' is outside the scenario's authorized "
                "requirement-local evidence"
            )

    leak_error = _check_foreign_leakage(content_all, authority)
    if leak_error is not None:
        return leak_error

    masked_expected = _mask_authorized_text(expected_result, authority)
    if _HEDGE.search(masked_expected):
        return "expected_result states an alternative/hedged outcome; one determinate outcome is required"

    literal_error = _check_literals(title, preconditions, steps, expected_result, authority)
    if literal_error is not None:
        return literal_error

    if authority.scenario.category == "security":
        # Rule J: the security predicate must be operationalized in steps
        # and/or expected_result — a title alone never satisfies it.
        operational = " ".join(steps) + " " + expected_result
        security_error = _check_security(operational, authority)
        if security_error is not None:
            return security_error

    return None


def _mask_authorized_text(text: str, authority: ScenarioAuthority) -> str:
    """Blank out authorized scope text so evidence-defined literals do not
    read as hedged outcomes (e.g. a source message that itself says 'or')."""

    masked = text
    sources = [
        source
        for source in (*authority.support_texts, *authority.own_texts)
        if source and len(source) <= _MAX_MASKABLE_TEXT
    ]
    sources.extend(
        _extract_literals([*authority.support_texts, *authority.own_texts])
    )
    for source in sorted(set(sources), key=len, reverse=True):
        masked = re.sub(re.escape(source), " ", masked, flags=re.IGNORECASE)
    return masked


def _extract_literals(texts: list[str]) -> list[str]:
    literals: list[str] = []
    for text in texts:
        literals.extend(_LITERAL_QUOTE_DOUBLE.findall(text))
        literals.extend(_LITERAL_QUOTE_SINGLE.findall(text))
        sample = _SAMPLE_VALUE.search(text)
        if sample:
            literals.append(sample.group(1))
    return [literal.strip() for literal in literals if literal.strip()]


def _check_literals(
    title: str,
    preconditions: list[str],
    steps: list[str],
    expected_result: str,
    authority: ScenarioAuthority,
) -> str | None:
    """Rule G: exact source literals stay exact; no draft/correction pairs."""

    authorized = [
        text for text in
        [*authority.support_texts, *authority.own_texts]
        if 0 < len(text) <= _MAX_MASKABLE_TEXT
    ]
    extracted = _extract_literals([*authority.support_texts, *authority.own_texts])
    authorized_literals = [literal.casefold() for literal in extracted]
    authorized_sources = [*authorized, *extracted]
    content_texts = [title, *preconditions, *steps, expected_result]
    content_literals = _extract_literals(content_texts)

    for literal in content_literals:
        normalized = literal.casefold()
        if normalized in authorized_literals:
            continue
        for source in authorized_sources:
            source_folded = source.casefold()
            if normalized == source_folded:
                break
            ratio = difflib.SequenceMatcher(None, normalized, source_folded).ratio()
            if ratio >= _CORRUPTION_RATIO:
                return (
                    f"literal {literal!r} alters authorized source text "
                    f"{source!r}; exact literals must be preserved"
                )
        else:
            looks_like_message = (
                " " in literal
                or re.search(
                    r"\b(?:invalid|error|failed|failure|required|cannot|tidak|"
                    r"gagal|salah|wajib)\b",
                    literal,
                    re.IGNORECASE,
                )
            )
            if looks_like_message and normalized not in authority.own.casefold():
                return (
                    f"literal {literal!r} is not authorized by the scenario's "
                    "evidence; invented message text is forbidden"
                )
    return None


def _check_foreign_leakage(content: str, authority: ScenarioAuthority) -> str | None:
    """Rules A/B: evidence bound to another requirement must not become content."""

    content_folded = content.casefold()
    own_folded = authority.own.casefold()
    for foreign in authority.foreign_texts:
        foreign_folded = foreign.casefold()
        if len(foreign_folded) < 10:
            continue
        if foreign_folded in content_folded and foreign_folded not in own_folded:
            return (
                "content reproduces evidence from another requirement "
                f"({foreign!r}); requirement locality is mandatory"
            )
    for literal in _extract_literals([content]):
        literal_folded = literal.casefold()
        if literal_folded in own_folded:
            continue
        for foreign in authority.foreign_texts:
            if literal_folded and literal_folded in foreign.casefold():
                return (
                    f"content uses literal {literal!r} that belongs to another "
                    "requirement's evidence"
                )
    return None


def _check_security(content: str, authority: ScenarioAuthority) -> str | None:
    """Rule J: category=security never authorizes a security claim by itself."""

    if not _SECURITY_PREDICATE.search(content):
        return (
            "hollow security content: no concrete security predicate is "
            "asserted; category=security alone is not evidence"
        )
    if not _SECURITY_PREDICATE.search(authority.support):
        return (
            "security claim is not supported by the scenario's authorized "
            "evidence; security must be evidence-bound"
        )
    return None
