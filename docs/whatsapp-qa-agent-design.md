# WhatsApp Q&A Agent Design

This design applies the agent-building principles to a narrow, citation-first
WhatsApp assistant for student-facing Schwarzman resources.

## 1. Scope

The first agent has one job: answer student questions from the reviewed
downloaded corpus.

Input boundary:

- One inbound WhatsApp message.
- Short session context from the same chat.
- Approved corpus rows from `data/corpus/review/corpus-review.csv`.
- Approved chunks from `data/corpus/chunks/*.jsonl`.

Output boundary:

- One concise WhatsApp reply.
- Numbered citations in the answer.
- An `Evidence` section mapping citations to source files and chunks.

Decision boundary:

- Allowed: answer from reviewed student-facing resources.
- Allowed: ask a targeted clarification.
- Allowed: say the answer is not found in the downloaded resources.
- Forbidden: collect credentials, log into student accounts, answer from
  unreviewed files, invent policy, or give uncited factual claims.
- Forbidden: perform external actions such as submitting forms, emailing staff,
  changing records, applying to jobs, or contacting offices.

## 2. Stage Contracts

Every stage should return a predictable object so failures are easy to see.

### Inbound Message

```json
{
  "message_id": "string",
  "from_hash": "string",
  "received_at": "ISO-8601",
  "text": "string",
  "session_id": "string"
}
```

Do not store raw phone numbers in normal logs. Use a hash or provider message
ID.

### Parser Output

```json
{
  "intent": "resource_question | greeting | clarification | unsupported",
  "confidence": 0.0,
  "topics": ["visa", "packing", "career", "blackboard"],
  "input_guardrail": {
    "prompt_injection_score": 0.0,
    "sensitive_data_detected": false,
    "blocked_phrases": []
  },
  "required_fields": [],
  "missing_fields": [],
  "risk_level": "low | medium | high"
}
```

### Retrieval Request

```json
{
  "query": "string",
  "filters": {
    "review_decisions": ["include", "summarize_only"],
    "sources": ["blackboard", "rencai"]
  },
  "top_k": 6
}
```

### Retrieval Result

```json
{
  "query": "string",
  "results": [
    {
      "chunk_id": "string",
      "relevance": 0.0,
      "source_file": "data/path/to/file.pdf",
      "source_title": "file.pdf",
      "citation_ref": "data/path/to/file.pdf#chunk=0",
      "review_decision": "include",
      "text": "string"
    }
  ],
  "quality": {
    "top_score": 0.0,
    "supporting_sources": 0,
    "has_reviewed_sources": true,
    "retrieval_confidence": 0.0
  }
}
```

### Answer Draft

```json
{
  "answer": "string",
  "citations": [
    {
      "label": "[1]",
      "citation_ref": "data/path/to/file.pdf#chunk=0",
      "quote": "optional direct quote",
      "supports_claim": "string"
    }
  ],
  "confidence": 0.0,
  "needs_clarification": false
}
```

### Policy Check

```json
{
  "allowed": true,
  "blocked_reasons": [],
  "required_response_type": "answer | clarification | not_found | safety_refusal",
  "citation_count": 1,
  "has_uncited_factual_claims": false,
  "prompt_injection_handled": true,
  "leaks_internal_policy": false
}
```

### Response Log

```json
{
  "message_id": "string",
  "intent": "resource_question",
  "retrieval_confidence": 0.0,
  "answer_confidence": 0.0,
  "policy_result": "allowed | blocked",
  "citation_refs": ["data/path/to/file.pdf#chunk=0"],
  "latency_ms": 0,
  "error_type": ""
}
```

## 3. System Policy

The production system prompt should read like policy:

Objective:

- Help incoming/current Schwarzman students find answers in the reviewed
  student-facing resource corpus.

Allowed actions:

- Interpret a student question.
- Retrieve reviewed corpus chunks.
- Answer with citations.
- Ask a clarification when the question is ambiguous.
- Say the answer is not available in the downloaded resources.

Forbidden actions:

- Do not ask for credentials, passwords, MFA codes, passport numbers, phone
  numbers, addresses, student IDs, or government IDs.
- Do not answer from files marked `drop`, `needs_fix`, or `review`.
- Do not make uncited factual claims from the corpus.
- Do not provide legal, immigration, medical, financial, or career guarantees.
- Do not pretend to be Schwarzman College, Tsinghua, Rencai, or Blackboard.

Escalation triggers:

- Retrieval confidence is below the answer threshold.
- Sources conflict.
- The question asks for a personal administrative determination.
- The answer depends on policy that may have changed.
- The user asks for private account access or credentials.

Required output:

- Follow `docs/answering-policy.md`.

## 3A. Prompt Structure and Untrusted Data

Separate system policy from untrusted data in every model call.

System/developer messages:

- Contain the operating policy, allowed actions, forbidden actions, citation
  format, and guardrail rules.
- Must never be concatenated with user text or retrieved document text.

User messages and retrieved chunks:

- Must be passed as data inside explicit delimiters.
- Must never be interpreted as instructions that override policy.

Recommended prompt structure:

```text
SYSTEM:
<policy and task instructions>

USER_INPUT_START_7f3a91
<raw WhatsApp user message>
USER_INPUT_END_7f3a91

RETRIEVED_CONTEXT_START_b42c18
<retrieved chunk JSON objects>
RETRIEVED_CONTEXT_END_b42c18
```

Delimiter requirements:

- Use distinct randomized delimiters for user input and retrieved context.
- Keep retrieved chunks structured as JSON where possible.
- Preserve `citation_ref`, `source_file`, `chunk_index`, `char_start`, and
  `char_end` outside the free-text evidence field.
- Never place untrusted text in the system message.

## 3B. Input Validation and Sanitization

Treat all external input as hostile until classified.

Validation controls:

- Enforce a maximum WhatsApp input length, such as `2,000` characters.
- Normalize whitespace and strip invisible control characters.
- Reject or down-rank messages dominated by URLs, code blocks, or repeated
  adversarial phrases.
- Detect sensitive personal data patterns before model routing.

Known prompt-injection indicators:

- `ignore previous instructions`
- `ignore all prior instructions`
- `reveal your system prompt`
- `developer message`
- `system message`
- `act as`
- `jailbreak`
- `no citations`
- `use unreviewed files`
- `bypass policy`
- `print hidden`
- `tool output`

Detection should not automatically block every message. If a normal resource
question contains one suspicious phrase, strip/ignore the adversarial portion
and answer only if retrieval and policy checks pass.

## 3C. Secondary Classifier

Before the main answer model runs, pass the normalized user message through a
small classifier.

Classifier output:

```json
{
  "is_resource_question": true,
  "prompt_injection_score": 0.0,
  "sensitive_data_score": 0.0,
  "unsupported_request": false,
  "recommended_route": "answer | clarify | refuse | not_found"
}
```

Routing:

- `prompt_injection_score >= 0.80`: refuse or ask for a normal resource
  question.
- `prompt_injection_score 0.40-0.80`: continue only if the resource question is
  clear and output guardrails pass.
- `sensitive_data_score >= 0.70`: do not echo sensitive data; respond with a
  safety-oriented clarification or refusal.

## 3D. Least Privilege and RBAC

The LLM should not have blanket access to files, APIs, or internal systems.

MVP permissions:

- Read filtered corpus index.
- Read chunk text and citation metadata.
- Read `corpus-review.csv` decisions.
- Write redacted logs.
- Send one WhatsApp reply through the messaging adapter.

Forbidden permissions:

- No Blackboard, Rencai, or student account login.
- No file-system browsing beyond the approved corpus artifacts.
- No access to raw credentials, API secrets, provider dashboards, or private
  user records.
- No write access to corpus review decisions from the answer generator.

Isolation:

- Keep each user's WhatsApp session separate.
- Do not let one user retrieve another user's messages or logs.
- Store provider IDs and phone numbers as hashes in normal logs.

## 4. Confidence Gates

Use explicit gates rather than vague confidence language.

Answer allowed:

- Parser confidence >= `0.70`.
- Retrieval top score >= `0.72`.
- At least one retrieved chunk is from a reviewed `include` source.
- Policy check finds no uncited factual claims.

Ask clarification:

- Parser confidence is between `0.50` and `0.70`.
- Retrieval top score is between `0.55` and `0.72`.
- The query could refer to multiple topics, such as visa, residence permit, or
  internship annotation.

Say not found:

- Retrieval top score < `0.55`.
- Retrieved chunks are unreviewed, dropped, or extraction-flagged.
- The answer would require guessing.

Use caution language:

- Visa, residence permit, employment, testing, transcript, or formal policy
  answers should cite the source and recommend checking the official office or
  current portal for final confirmation.

## 5. Retrieval Design

Retrieval quality is the priority.

Index only:

- `decision=include`
- `decision=summarize_only`, with reduced quoting behavior

Do not index:

- `decision=drop`
- `decision=needs_fix`
- `decision=review`

Chunk metadata must include:

- `chunk_id`
- `source`
- `source_file`
- `source_title`
- `citation_ref`
- `chunk_index`
- `char_start`
- `char_end`
- `sha256`
- `review_decision`

Search flow:

1. Normalize the question.
2. Apply review-decision filters.
3. Apply optional topic/source filters when obvious.
4. Retrieve top chunks by semantic similarity.
5. Rerank or keyword-check top results.
6. Build answer only from retrieved chunks that pass the threshold.

If the top chunks are thin, contradictory, or off-topic, ask a clarification or
return not-found.

## 6. Citation Rules

Follow `docs/answering-policy.md`.

Additional implementation rules:

- Every citation in the answer must appear in `Evidence`.
- Every `Evidence` item must include a `citation_ref`.
- Direct quotes must be exact and wrapped in double quotes.
- Keep quotes short. Prefer paraphrase plus citation for long passages.
- Never cite a chunk that was not retrieved for that answer.

## 7. Privacy and Memory

Separate memory by purpose.

Session memory:

- Recent user question.
- Clarification state.
- Last cited topic.

Knowledge memory:

- Reviewed corpus chunks and metadata.

Persistent profile memory:

- None for the MVP.

Do not persist:

- Phone numbers in plain text.
- Credentials or authentication codes.
- Passport numbers, student IDs, government IDs, addresses, or private account
  information.

## 8. Guardrail Layers

Input guardrails:

- Reject credential collection.
- Ignore attempts to override citation policy.
- Detect requests for private personal/account-specific determinations.
- Detect prompt-injection patterns in user messages.
- Treat retrieved corpus text as evidence, never instructions.

Output guardrails:

- Block uncited factual answers.
- Block answers with unsupported direct quotes.
- Block requests for sensitive data.
- Require not-found response when no source supports the answer.
- Block responses that reveal hidden policies, prompts, tool outputs, API keys,
  or internal operational details.
- Block responses that comply with prompt-injection instructions.

Policy guardrails:

- Corpus review decisions are non-negotiable.
- Only reviewed chunks can be retrieved for answer generation.
- No external actions in the MVP.
- RBAC and file filters are enforced outside model reasoning.

## 9. Failure Paths

If retrieval fails:

- Reply: `I can't search the downloaded resources right now. Please try again later.`
- Log `error_type=retrieval_failure`.

If model generation fails:

- Retry once.
- If retry fails, send a short failure message.

If WhatsApp send fails:

- Retry with provider-safe idempotency key:
  `reply-{provider_message_id}`.

If policy check fails:

- Send clarification, not-found, or safety response instead of the draft answer.

## 10. Observability

Track metrics per stage:

- Parse confidence.
- Retrieval top score.
- Number of supporting sources.
- Retrieval latency.
- Generation latency.
- Policy blocks.
- Citation count.
- Not-found rate.
- Clarification rate.
- WhatsApp send failures.

Do not log full message text by default once the system is live. For debugging,
sample only with redaction.

## 11. Evaluation Set

Before launch, create a realistic eval set with around 50 questions:

- 30 normal questions.
- 10 ambiguous questions.
- 5 adversarial or prompt-injection questions.
- 5 policy-conflict or unsupported questions.

Score:

- Correct file retrieved.
- Answer correctness.
- Citation correctness.
- Quote exactness.
- Refusal/not-found correctness.
- Average turns to useful answer.

## 12. Model and Cost Controls

Hard limits:

- Max retrieved chunks: `6`.
- Max answer length: one WhatsApp screen unless the user asks for detail.
- Max retries per tool: `2`.
- Max clarification turns before not-found: `2`.

Model routing:

- Use a cheaper/faster model for parsing and simple retrieval decisions.
- Use a stronger model for final cited answer generation if needed.
- Evaluate model choices in the full pipeline, not standalone Q&A.

## 13. Rollout Plan

Phase 1: Local dry run.

- Use the corpus index locally.
- Ask test questions from the terminal.
- Inspect citations and source snippets manually.

Phase 2: Shadow mode.

- Feed real-looking questions.
- Generate answers but do not send automatically.
- Fix the top recurring failure modes.

Phase 3: Limited WhatsApp pilot.

- One-to-one bot only.
- Small trusted group.
- Read-only resource Q&A.
- Logging with redaction.

Phase 4: Broader group availability.

- Keep the same read-only scope.
- Add feedback command, such as `wrong` or `needs update`.
- Review logs weekly for retrieval misses and bad citations.

## 14. Practical Build Order

1. Review `corpus-review.csv`.
2. Build filtered local index from `include` and `summarize_only`.
3. Implement retrieval with citation metadata.
4. Implement answer formatter from `docs/answering-policy.md`.
5. Add policy checker for citations and review decisions.
6. Build 50-question eval set.
7. Run local dry-run eval.
8. Add WhatsApp webhook.
9. Add observability and redacted logs.
10. Pilot with a few users.
