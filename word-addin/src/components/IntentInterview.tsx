import {
  answerForQuestion,
  isOtherAnswer,
  isQuestionAnswered,
} from "@/lib/intentInterview"
import type {
  DocumentIntentInterview,
  IntentAnswer,
  IntentQuestion,
} from "@/lib/types"
import type { MessageKey } from "@/i18n/messages"

type Translate = (key: MessageKey, params?: Record<string, string | number>) => string

export function IntentInterviewCard(props: {
  interview: DocumentIntentInterview
  answers: IntentAnswer[]
  index: number
  canStart: boolean
  t: Translate
  onSelect: (questionId: string, value: string) => void
  onToggle: (questionId: string, value: string) => void
  onFreeText: (questionId: string, value: string) => void
  onSelectOther: (questionId: string) => void
  onOtherText: (questionId: string, value: string) => void
  onBack: () => void
  onNext: () => void
  onStart: () => void
  onRestart: () => void
}) {
  const total = props.interview.questions.length
  if (total === 0) {
    return (
      <section className="interview" aria-label={props.t("interviewHeading")}>
        <h2>{props.t("interviewHeading")}</h2>
        <p className="hint">{props.t("interviewEmpty")}</p>
        <div className="interview-nav">
          <button
            type="button"
            className="primary"
            onClick={props.onStart}
            disabled={!props.canStart}
          >
            {props.t("review")}
          </button>
        </div>
        <button type="button" className="link" onClick={props.onRestart}>
          {props.t("interviewRestart")}
        </button>
      </section>
    )
  }
  const question = props.interview.questions[props.index]
  if (!question) {
    return null
  }
  const answer = answerForQuestion(props.answers, question.id)
  const canNext =
    props.index < total - 1 &&
    (!question.required || isQuestionAnswered(question, answer))
  return (
    <section className="interview" aria-label={props.t("interviewHeading")}>
      <h2>{props.t("interviewHeading")}</h2>
      <p className="interview-progress">
        {props.t("interviewQuestionProgress", {
          current: props.index + 1,
          total,
        })}
      </p>
      <p className="interview-question">{question.text}</p>
      <QuestionInputs
        question={question}
        answer={answer}
        t={props.t}
        onSelect={props.onSelect}
        onToggle={props.onToggle}
        onFreeText={props.onFreeText}
        onSelectOther={props.onSelectOther}
        onOtherText={props.onOtherText}
      />
      <div className="interview-nav">
        <button type="button" onClick={props.onBack} disabled={props.index === 0}>
          {props.t("interviewBack")}
        </button>
        {props.index < total - 1 ? (
          <button type="button" onClick={props.onNext} disabled={!canNext}>
            {props.t("interviewNext")}
          </button>
        ) : null}
        <button
          type="button"
          className="primary"
          onClick={props.onStart}
          disabled={!props.canStart}
        >
          {props.t("review")}
        </button>
      </div>
      <button type="button" className="link" onClick={props.onRestart}>
        {props.t("interviewRestart")}
      </button>
    </section>
  )
}

function QuestionInputs(props: {
  question: IntentQuestion
  answer: IntentAnswer | undefined
  t: Translate
  onSelect: (questionId: string, value: string) => void
  onToggle: (questionId: string, value: string) => void
  onFreeText: (questionId: string, value: string) => void
  onSelectOther: (questionId: string) => void
  onOtherText: (questionId: string, value: string) => void
}) {
  const selected = new Set(props.answer?.selected_values ?? [])
  const otherSelected = isOtherAnswer(props.answer)
  switch (props.question.type) {
    case "single_choice":
      return (
        <div className="interview-options">
          {props.question.options.map((option) => (
            <label
              key={option.value}
              className="interview-option"
              data-selected={selected.has(option.value) ? "true" : "false"}
            >
              <input
                type="radio"
                name={props.question.id}
                checked={selected.has(option.value)}
                onChange={() => props.onSelect(props.question.id, option.value)}
              />
              {option.label}
            </label>
          ))}
          <OtherChoice
            questionId={props.question.id}
            inputType="radio"
            selected={otherSelected}
            freeText={props.answer?.free_text ?? ""}
            t={props.t}
            onSelectOther={props.onSelectOther}
            onOtherText={props.onOtherText}
          />
        </div>
      )
    case "multi_choice":
      return (
        <div className="interview-options">
          {props.question.options.map((option) => (
            <label
              key={option.value}
              className="interview-option"
              data-selected={selected.has(option.value) ? "true" : "false"}
            >
              <input
                type="checkbox"
                checked={selected.has(option.value)}
                onChange={() => props.onToggle(props.question.id, option.value)}
              />
              {option.label}
            </label>
          ))}
          <OtherChoice
            questionId={props.question.id}
            inputType="checkbox"
            selected={otherSelected}
            freeText={props.answer?.free_text ?? ""}
            t={props.t}
            onSelectOther={props.onSelectOther}
            onOtherText={props.onOtherText}
          />
        </div>
      )
    case "free_text":
      return (
        <textarea
          className="interview-free-text"
          rows={3}
          value={props.answer?.free_text ?? ""}
          onChange={(event) => props.onFreeText(props.question.id, event.target.value)}
        />
      )
    default: {
      const _exhaustive: never = props.question.type
      return _exhaustive
    }
  }
}

function OtherChoice(props: {
  questionId: string
  inputType: "radio" | "checkbox"
  selected: boolean
  freeText: string
  t: Translate
  onSelectOther: (questionId: string) => void
  onOtherText: (questionId: string, value: string) => void
}) {
  return (
    <div className="interview-other">
      <label
        className="interview-option"
        data-selected={props.selected ? "true" : "false"}
      >
        <input
          type={props.inputType}
          name={props.inputType === "radio" ? props.questionId : undefined}
          checked={props.selected}
          onChange={() => props.onSelectOther(props.questionId)}
        />
        {props.t("interviewOther")}
      </label>
      {props.selected ? (
        <textarea
          className="interview-free-text interview-other-text"
          rows={3}
          value={props.freeText}
          onChange={(event) => props.onOtherText(props.questionId, event.target.value)}
          placeholder={props.t("interviewOtherPlaceholder")}
          aria-label={props.t("interviewOther")}
        />
      ) : null}
    </div>
  )
}
