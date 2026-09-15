import React, { useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  Activity,
  ArrowDownToLine,
  ArrowLeft,
  ArrowRight,
  AudioLines,
  BookOpen,
  Check,
  CheckCheck,
  ChevronLeft,
  ChevronRight,
  CircleHelp,
  Clock3,
  FileText,
  Film,
  FolderOpen,
  LayoutDashboard,
  LoaderCircle,
  LockKeyhole,
  MonitorPlay,
  MoreHorizontal,
  Plus,
  Search,
  Settings2,
  ShieldCheck,
  Sparkles,
  Upload,
  X,
  AlertTriangle,
  Play,
  WandSparkles,
} from "lucide-react";
import "./styles.css";

type Knowledge = {
  question: string;
  options: string[];
  correct: number;
  explanation: string;
};
const CUE_LABEL_LIMIT = 120;
type VisualCue = {
  label: string;
  x: number;
  y: number;
  width?: number;
  height?: number;
  paragraph?: number;
};
type EvidencePassage = { id: string; text: string };
type EvidenceCollection =
  EvidencePassage[] | Record<string, EvidencePassage | string>;
type EvaluationFinding = {
  id?: string;
  origin?: string;
  severity?: string;
  category?: string;
  message?: string;
  type?: string;
  reason?: string;
  verification_reason?: string;
  verification_source_ids?: string[];
  verification_draft_ids?: string[];
  source_ids?: string[];
  draft_ids?: string[];
  source_spans?: EvidencePassage[];
  draft_spans?: EvidencePassage[];
  source_quote?: string;
  draft_quote?: string;
  remediation?: string;
  evidence_ids?: string[];
};
type ScriptEvaluation = {
  stale?: boolean;
  stale_reasons?: string[];
  model_identity?: { name: string; digest: string };
  audience?: string;
  version?: string;
  evaluation_protocol?: string | Record<string, unknown>;
  auto_revision_allowed?: boolean;
  review_hints?: (EvaluationFinding | string)[];
  uncertain_findings?: EvaluationFinding[];
  dismissed_findings?: EvaluationFinding[];
  evidence_audit?: {
    source_passages?: EvidenceCollection;
    draft_passages?: EvidenceCollection;
  };
  state?: string;
  summary?: string;
  model?: string;
  assessed_revision?: number;
  findings?: EvaluationFinding[];
  clinical_validation?: boolean;
  requires_practitioner_review?: boolean;
};
type Slide = {
  number: number;
  title: string;
  text: string;
  notes: string;
  tables: string[][][];
  image_count: number;
  sources: string[];
  narration: string;
  draft_origin: string;
  flags: string[];
  ai_flags?: string[];
  approved: boolean;
  revision: number;
  reviewer: string;
  image: boolean;
  knowledge?: Knowledge | null;
  visual_cues?: VisualCue[];
  visual_text?: string;
  source_reviewed?: boolean;
  ocr?: { text: string; lines: unknown[]; engine: string };
  evaluation?: ScriptEvaluation | null;
  evaluation_error?: string | null;
  draft_preview?: {
    url: string;
    revision: number;
    engine: string;
    voice: string;
    delivery: string;
    duration: number;
  };
};
type Job = {
  status: string;
  kind?: string;
  progress?: number;
  message?: string;
};
type Export = {
  id: string;
  created_at: string;
  duration: number;
  settings: {
    start: number;
    end: number;
    visual_style?: "whiteboard" | "studio" | "focus" | "powerpoint";
  };
};
type Project = {
  id: string;
  name: string;
  filename: string;
  slides: Slide[];
  audience: string;
  specialty: string;
  created_at: string;
  updated_at: string;
  job: Job;
  exports: Export[];
  history: { at: string; action: string; detail: string }[];
};
type Summary = Omit<Project, "slides"> & {
  slide_count: number;
  approved_count: number;
};
type Health = {
  models: string[];
  ollama_error: string | null;
  ffmpeg: boolean;
  renderer: boolean;
  renderer_name: string;
  powerpoint_animation?: boolean;
  kokoro: boolean;
  qwen_tts?: boolean;
  ocr: boolean;
  piper: boolean;
  windows_voice: boolean;
  data_path: string;
  version: string;
};
const VOICES = [
  ["af_heart", "Warm American (female)"],
  ["af_bella", "Conversational American (female)"],
  ["am_michael", "Clear American (male)"],
  ["bf_emma", "British narrator (female)"],
] as const;
const voiceReady = (health: Health | null, engine: string) =>
  engine === "qwen"
    ? !!health?.qwen_tts
    : engine === "kokoro"
      ? !!health?.kokoro
      : engine === "piper"
        ? !!health?.piper
        : engine === "windows" && !!health?.windows_voice;
const EMPTY_CHECK: Knowledge = {
  question: "",
  options: ["", "", ""],
  correct: 0,
  explanation: "",
};
const api = async <T,>(path: string, init?: RequestInit): Promise<T> => {
  const r = await fetch("/api" + path, {
    ...init,
    headers:
      init?.body instanceof FormData
        ? {}
        : { "Content-Type": "application/json", ...init?.headers },
  });
  if (!r.ok) {
    const e = await r.json().catch(() => ({ detail: r.statusText }));
    throw new Error(
      typeof e.detail === "string" ? e.detail : JSON.stringify(e.detail),
    );
  }
  return r.json();
};
const post = <T,>(path: string, body: unknown = {}) =>
  api<T>(path, { method: "POST", body: JSON.stringify(body) });
const busy = (p: Project | null) =>
  ["running", "queued"].includes(p?.job.status || "");
const date = (s: string) =>
  new Date(s).toLocaleDateString(undefined, { month: "short", day: "numeric" });
const duration = (s: number) => {
  const seconds = Math.max(0, Math.round(s));
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
};

function App() {
  const [projects, setProjects] = useState<Summary[]>([]),
    [project, setProject] = useState<Project | null>(null),
    [health, setHealth] = useState<Health | null>(null);
  const [page, setPage] = useState("library"),
    [modal, setModal] = useState(""),
    [error, setError] = useState(""),
    [notice, setNotice] = useState(""),
    [loading, setLoading] = useState(false);
  const [search, setSearch] = useState(""),
    [index, setIndex] = useState(0),
    [script, setScript] = useState(""),
    [knowledge, setKnowledge] = useState<Knowledge>(EMPTY_CHECK),
    [visualCues, setVisualCues] = useState<VisualCue[]>([]),
    [cuePlacement, setCuePlacement] = useState<number | null>(null),
    [visualText, setVisualText] = useState(""),
    [sourceReviewed, setSourceReviewed] = useState(false);
  const [reviewer, setReviewer] = useState(
      localStorage.getItem("narrate-reviewer") || "",
    ),
    [ack, setAck] = useState(false),
    [sourceTab, setSourceTab] = useState("text"),
    [editorTab, setEditorTab] = useState("narration");
  const [narrationStyle, setNarrationStyle] = useState<
    "conversational" | "concise"
  >("conversational");
  const [model, setModel] = useState(""),
    [engine, setEngine] = useState("kokoro"),
    [voice, setVoice] = useState("af_heart"),
    [qwenVoice, setQwenVoice] = useState("Aiden"),
    [delivery, setDelivery] = useState<"warm" | "clear" | "engaging">("warm"),
    [rate, setRate] = useState(1),
    [rangeStart, setRangeStart] = useState(1),
    [rangeEnd, setRangeEnd] = useState(10),
    [burn, setBurn] = useState(true),
    [visualStyle, setVisualStyle] = useState<
      "whiteboard" | "studio" | "focus" | "powerpoint"
    >("focus");
  const [filter, setFilter] = useState("all"),
    [drag, setDrag] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null),
    dialogRef = useRef<HTMLElement>(null),
    pending = useRef(false),
    loadingRef = useRef(false),
    engineChosen = useRef(false),
    modelChosen = useRef(false),
    preserveSlideEdits = useRef(false);
  loadingRef.current = loading;
  const slide = project?.slides[index];
  const drafting = busy(project) && project?.job.kind === "draft";
  const evaluating = busy(project) && project?.job.kind === "evaluate";
  const modelAvailable = !!health?.models.includes(model);
  const narrationWordCount = script.trim()
    ? script.trim().split(/\s+/).length
    : 0;
  const narrationSentences = Array.from(
    new Intl.Segmenter("en", { granularity: "sentence" }).segment(script),
  )
    .map((part) => part.segment.trim())
    .filter(Boolean);
  const sentenceWordCounts = narrationSentences.map(
    (sentence) => sentence.split(/\s+/).length,
  );
  const averageSentenceWords = sentenceWordCounts.length
    ? Math.round(
        sentenceWordCounts.reduce((sum, count) => sum + count, 0) /
          sentenceWordCounts.length,
      )
    : 0;
  const longSentenceCount = sentenceWordCounts.filter(
    (count) => count > 26,
  ).length;
  const sourceDirty =
    !!slide &&
    (visualText !== (slide.visual_text || "") ||
      sourceReviewed !== !!slide.source_reviewed);
  const contentDirty =
    !!slide &&
    (script !== slide.narration ||
      JSON.stringify(knowledge) !==
        JSON.stringify(slide.knowledge || EMPTY_CHECK) ||
      JSON.stringify(visualCues) !== JSON.stringify(slide.visual_cues || []));
  const dirty = contentDirty || sourceDirty;
  const reload = async () => setProjects(await api<Summary[]>("/projects"));
  const loadHealth = async () => {
    const h = await api<Health>("/health");
    setHealth(h);
    if (!modelChosen.current)
      setModel(
        h.models.includes("qwen3.5:9b") ? "qwen3.5:9b" : h.models[0] || "",
      );
    if (!engineChosen.current) {
      setEngine(
        h.qwen_tts
          ? "qwen"
          : h.kokoro
            ? "kokoro"
            : h.piper
              ? "piper"
              : h.windows_voice
                ? "windows"
                : "kokoro",
      );
    }
  };
  const perform = async (fn: () => Promise<void>) => {
    if (pending.current) return;
    pending.current = true;
    setError("");
    setLoading(true);
    try {
      await fn();
    } catch (e) {
      setError(
        e instanceof Error
          ? e.message
          : "Something went wrong. Please try again.",
      );
    } finally {
      pending.current = false;
      setLoading(false);
    }
  };
  useEffect(() => {
    void perform(async () => {
      await Promise.all([reload(), loadHealth()]);
    });
  }, []);
  useEffect(() => {
    if (slide) {
      if (preserveSlideEdits.current) {
        preserveSlideEdits.current = false;
        return;
      }
      setScript(slide.narration);
      setKnowledge(slide.knowledge || EMPTY_CHECK);
      setVisualCues(slide.visual_cues || []);
      setVisualText(slide.visual_text || "");
      setSourceReviewed(!!slide.source_reviewed);
      setCuePlacement(null);
      setAck(false);
    }
  }, [project?.id, index, slide?.revision]);
  useEffect(() => {
    if (!project || !busy(project)) return;
    let active = true,
      inFlight = false;
    const t = setInterval(async () => {
      if (inFlight) return;
      inFlight = true;
      try {
        const p = await api<Project>(`/projects/${project.id}`);
        if (!active) return;
        setProject(p);
        if (!busy(p)) await reload();
      } catch (e) {
        if (active)
          setError(
            e instanceof Error
              ? e.message
              : "Could not refresh processing status.",
          );
      } finally {
        inFlight = false;
      }
    }, 1500);
    return () => {
      active = false;
      clearInterval(t);
    };
  }, [project?.id, project?.job.status]);
  useEffect(() => {
    if (!notice) return;
    const t = setTimeout(() => setNotice(""), 4000);
    return () => clearTimeout(t);
  }, [notice]);
  useEffect(() => {
    const f = (e: BeforeUnloadEvent) => {
      if (dirty) {
        e.preventDefault();
        e.returnValue = "";
      }
    };
    window.addEventListener("beforeunload", f);
    return () => window.removeEventListener("beforeunload", f);
  }, [dirty]);
  useEffect(() => {
    if (!modal) return;
    const previous =
      document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null;
    const dialog = dialogRef.current;
    const background = Array.from(
      document.querySelectorAll<HTMLElement>(".app > .sidebar, .app > .main"),
    );
    background.forEach((element) => {
      element.inert = true;
    });
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    dialog?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        if (!loadingRef.current) setModal("");
        return;
      }
      if (event.key !== "Tab" || !dialog) return;
      const focusable = Array.from(
        dialog.querySelectorAll<HTMLElement>(
          'button:not(:disabled), a[href], input:not(:disabled):not([type="hidden"]), select:not(:disabled), textarea:not(:disabled), [tabindex="0"]',
        ),
      ).filter((element) => element.getClientRects().length > 0);
      const first = focusable[0],
        last = focusable[focusable.length - 1];
      if (!first) {
        event.preventDefault();
        dialog.focus();
        return;
      }
      if (
        event.shiftKey &&
        (document.activeElement === first || document.activeElement === dialog)
      ) {
        event.preventDefault();
        last.focus();
      } else if (
        !event.shiftKey &&
        (document.activeElement === last || document.activeElement === dialog)
      ) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => {
      background.forEach((element) => {
        element.inert = false;
      });
      document.body.style.overflow = overflow;
      document.removeEventListener("keydown", onKey);
      if (previous?.isConnected) previous.focus();
    };
  }, [modal]);
  const leave = () => {
    if (pending.current) return false;
    if (!dirty) return true;
    if (
      !window.confirm(
        "You have unsaved narration, image text, knowledge check, or visual story edits. Discard them?",
      )
    )
      return false;
    if (slide) {
      setScript(slide.narration);
      setKnowledge(slide.knowledge || EMPTY_CHECK);
      setVisualCues(slide.visual_cues || []);
      setVisualText(slide.visual_text || "");
      setSourceReviewed(!!slide.source_reviewed);
      setCuePlacement(null);
      setAck(false);
    }
    return true;
  };
  const open = async (id: string) => {
    if (!leave()) return;
    await perform(async () => {
      const p = await api<Project>(`/projects/${id}`);
      setProject(p);
      setIndex(0);
      setPage("editor");
      setRangeStart(1);
      setRangeEnd(Math.min(10, p.slides.length));
    });
  };
  const upload = async (file?: File) => {
    if (!file || pending.current) return;
    if (!/\.ppt[xm]$/i.test(file.name)) {
      setError("Choose a PowerPoint file ending in .pptx or .pptm.");
      return;
    }
    if (file.size > 150 * 1024 * 1024) {
      setError("This file exceeds the 150 MB import limit.");
      return;
    }
    if (!leave()) return;
    await perform(async () => {
      const form = new FormData();
      form.append("file", file);
      const p = await api<Project>("/projects", { method: "POST", body: form });
      setProject(p);
      setIndex(0);
      setPage("editor");
      setModal("");
      setRangeStart(1);
      setRangeEnd(Math.min(10, p.slides.length));
      await reload();
      setNotice(
        `Imported ${p.slides.length} slides. Render previews to begin reviewing.`,
      );
    });
  };
  const action = async (path: string, body: unknown = {}) => {
    if (!project) return;
    await perform(async () =>
      setProject(await post<Project>(`/projects/${project.id}${path}`, body)),
    );
  };
  const save = async () => {
    if (!project || !slide) return;
    if (
      visualCues.some(
        (cue) =>
          !cue.label.trim() ||
          cue.label.length > CUE_LABEL_LIMIT ||
          !Number.isFinite(cue.x) ||
          !Number.isFinite(cue.y) ||
          cue.x < 0 ||
          cue.x > 1 ||
          cue.y < 0 ||
          cue.y > 1 ||
          !Number.isFinite(cue.width ?? 0.24) ||
          !Number.isFinite(cue.height ?? 0.24) ||
          (cue.width ?? 0.24) < 0.02 ||
          (cue.width ?? 0.24) > 1 ||
          (cue.height ?? 0.24) < 0.02 ||
          (cue.height ?? 0.24) > 1,
      )
    ) {
      setError(
        "Each visual cue needs a label, a position within the source image, and a region size between 2% and 100%.",
      );
      return;
    }
    await perform(async () => {
      let updated = project;
      try {
        if (sourceDirty)
          updated = await api<Project>(
            `/projects/${project.id}/slides/${slide.number}/source`,
            {
              method: "PUT",
              body: JSON.stringify({
                revision: slide.revision,
                visual_text: visualText,
                source_reviewed: sourceReviewed,
              }),
            },
          );
        if (contentDirty) {
          const revision = updated.slides.find(
            (item) => item.number === slide.number,
          )?.revision;
          if (revision === undefined)
            throw new Error(
              "The saved source revision could not be found. Reload the project before saving.",
            );
          updated = await api<Project>(
            `/projects/${project.id}/slides/${slide.number}`,
            {
              method: "PUT",
              body: JSON.stringify({
                narration: script,
                revision,
                knowledge: knowledge.question.trim() ? knowledge : null,
                visual_cues: visualCues,
              }),
            },
          );
        }
        setProject(updated);
        setNotice("Saved. Review this revision before approval.");
      } catch (error) {
        // A successful source save must not invalidate retrying pending script edits.
        if (updated !== project) {
          preserveSlideEdits.current = true;
          setProject(updated);
        }
        throw error;
      }
    });
  };
  const approved = project?.slides.filter((s) => s.approved).length || 0;
  const total = projects.reduce((n, p) => n + p.slide_count, 0);
  const activeExports = project?.exports || [];
  const selectSlide = (n: number) => {
    if (n === index) return;
    if (leave()) {
      setIndex(n);
      setSourceTab("text");
    }
  };
  const nav = (next: string) => {
    if (next === page) return;
    if (leave()) {
      setPage(next);
      if (next === "library") void perform(reload);
      if (next === "setup") void perform(loadHealth);
    }
  };
  return (
    <div className="app">
      <aside className="sidebar">
        <button
          className="brand"
          onClick={() => nav("library")}
          aria-label="Narrate Studio home"
        >
          <span className="brand-mark">
            <AudioLines size={24} />
          </span>
          <span>
            Narrate<span className="brand-sub">MEDICAL STUDIO</span>
          </span>
        </button>
        <div className="workspace-label">YOUR WORKSPACE</div>
        <nav>
          <button
            className={page === "library" ? "nav-item selected" : "nav-item"}
            onClick={() => nav("library")}
          >
            <LayoutDashboard size={18} />
            Presentations
          </button>
          <button
            className={page === "editor" ? "nav-item selected" : "nav-item"}
            disabled={!project}
            onClick={() => nav("editor")}
          >
            <Film size={18} />
            Lesson editor
          </button>
          <button
            className={page === "exports" ? "nav-item selected" : "nav-item"}
            disabled={!project}
            onClick={() => nav("exports")}
          >
            <MonitorPlay size={18} />
            Exports{" "}
            {activeExports.length > 0 && (
              <span className="count">{activeExports.length}</span>
            )}
          </button>
        </nav>
        <div className="sidebar-divider" />
        <div className="workspace-label">STUDIO</div>
        <button
          className={page === "setup" ? "nav-item selected" : "nav-item"}
          onClick={() => nav("setup")}
        >
          <Settings2 size={18} />
          Setup & preferences
        </button>
        <button className="nav-item" onClick={() => setModal("guide")}>
          <CircleHelp size={18} />
          Quick guide
        </button>
        <div className="privacy-card">
          <div className="privacy-icon">
            <LockKeyhole size={18} />
            <span className="green-dot" />
          </div>
          <strong>Your work stays here.</strong>
          <p>
            Local AI. Local storage.
            <br />
            No cloud processing.
          </p>
          <span className="small-label">OFFLINE WORKSPACE</span>
        </div>
        <div className="profile">
          <span className="avatar">
            {reviewer ? reviewer.slice(0, 2).toUpperCase() : "MD"}
          </span>
          <div>
            <strong>{reviewer || "Medical educator"}</strong>
            <span>Personal workspace</span>
          </div>
        </div>
      </aside>
      <main className="main" aria-busy={loading}>
        <header className="topbar">
          <div className="breadcrumb">
            Workspace <ChevronRight size={14} />
            <strong>
              {page === "editor"
                ? project?.name
                : page === "setup"
                  ? "Setup & preferences"
                  : page === "exports"
                    ? "Lesson exports"
                    : "Presentations"}
            </strong>
          </div>
          <div className="top-actions">
            <span className="offline-pill">
              <span className="green-dot" /> Running locally
            </span>
            <button
              className="icon-button"
              aria-label="Open quick guide"
              onClick={() => setModal("guide")}
            >
              <CircleHelp size={19} />
            </button>
          </div>
        </header>
        {error && !modal && (
          <div className="error-banner" role="alert">
            <AlertTriangle size={18} />
            <span>{error}</span>
            <button
              className="icon-button"
              aria-label="Dismiss error"
              onClick={() => setError("")}
            >
              <X size={16} />
            </button>
          </div>
        )}
        {loading && (
          <div className="loading-strip" role="status">
            <LoaderCircle className="spin" size={15} /> Working locally…
          </div>
        )}
        {notice && (
          <div className="toast" role="status">
            <Check size={18} />
            {notice}
          </div>
        )}
        {page === "library" && (
          <div className="page library">
            <div className="page-heading">
              <div>
                <div className="eyebrow">THE MEDICAL CREATOR WORKSPACE</div>
                <h1>Your production studio.</h1>
                <p>
                  Create narrated, interactive lessons. Built for medical
                  education.
                </p>
              </div>
              <button
                className="button primary"
                onClick={() => setModal("import")}
              >
                <Plus size={18} />
                New presentation
              </button>
            </div>
            <section className="hero cinematic-hero">
              <div className="hero-copy">
                <span className="hero-label">
                  <span className="studio-live-dot" /> EXPERTISE, IN MOTION
                </span>
                <h2>
                  Your next
                  <br />
                  masterclass
                  <br />
                  <em>starts here.</em>
                </h2>
                <p>
                  Give clinical knowledge a voice. Shape the story, build
                  learning moments, and create a lesson worth paying attention
                  to.
                </p>
                <button
                  className="button dark"
                  onClick={() => setModal("import")}
                >
                  <Plus size={18} /> Create a lesson <ArrowRight size={17} />
                </button>
                <span className="hero-foot">
                  <LockKeyhole size={14} /> Your device. Your expertise. Your
                  studio.
                </span>
              </div>
              <div className="production-preview" aria-hidden="true">
                <div className="production-chrome">
                  <span>
                    <span className="studio-live-dot" /> THE LEARNING EXPERIENCE
                  </span>
                  <span>STUDIO / 01</span>
                </div>
                <div className="production-screen">
                  <div className="clinical-orbit orbit-one" />
                  <div className="clinical-orbit orbit-two" />
                  <div className="clinical-symbol">
                    <Activity size={106} strokeWidth={1} />
                  </div>
                  <span className="screen-kicker">MAKE THE COMPLEX CLICK</span>
                  <strong>
                    Clinical insight.
                    <br />
                    <em>Lasting understanding.</em>
                  </strong>
                  <div className="screen-tags">
                    <span>
                      <AudioLines size={13} /> Narrated
                    </span>
                    <span>
                      <CircleHelp size={13} /> Interactive
                    </span>
                  </div>
                </div>
                <div className="production-timeline">
                  <div className="timeline-label">
                    <Film size={13} />
                    <span>THE STORY</span>
                    <span>3 LEARNING MOMENTS</span>
                  </div>
                  <div className="story-track">
                    <span>01 · Set the scene</span>
                    <span>02 · Explain</span>
                    <span>03 · Apply</span>
                  </div>
                  <div className="production-wave">
                    {Array.from({ length: 48 }, (_, i) => (
                      <i
                        key={i}
                        style={{
                          height: `${5 + ((i * 17) % 22)}px`,
                          animationDelay: `${i * 35}ms`,
                        }}
                      />
                    ))}
                  </div>
                </div>
                <div className="production-callout">
                  <ShieldCheck size={16} />
                  <span>Built around expert review</span>
                </div>
              </div>
            </section>
            <div
              className="studio-workflow"
              aria-label="Lesson creation workflow"
            >
              <div>
                <span>01</span>
                <div>
                  <strong>Bring your source</strong>
                  <p>Slides, visuals, clinical expertise.</p>
                </div>
                <Upload size={18} />
              </div>
              <div>
                <span>02</span>
                <div>
                  <strong>Direct the lesson</strong>
                  <p>Narration, pace, learning checks.</p>
                </div>
                <AudioLines size={18} />
              </div>
              <div>
                <span>03</span>
                <div>
                  <strong>Review. Then share.</strong>
                  <p>One lesson. Video + interaction.</p>
                </div>
                <MonitorPlay size={18} />
              </div>
            </div>
            <div className="stats">
              <div>
                <span className="stat-icon mint">
                  <FolderOpen size={20} />
                </span>
                <div>
                  <strong>{projects.length}</strong>
                  <span>Presentations</span>
                </div>
              </div>
              <div>
                <span className="stat-icon lavender">
                  <Film size={20} />
                </span>
                <div>
                  <strong>{total}</strong>
                  <span>Slides imported</span>
                </div>
              </div>
              <div>
                <span className="stat-icon peach">
                  <ShieldCheck size={20} />
                </span>
                <div>
                  <strong>
                    {projects.reduce((n, p) => n + p.approved_count, 0)}
                  </strong>
                  <span>Slides reviewed</span>
                </div>
              </div>
              <div>
                <span className="stat-icon blue">
                  <MonitorPlay size={20} />
                </span>
                <div>
                  <strong>
                    {projects.reduce((n, p) => n + p.exports.length, 0)}
                  </strong>
                  <span>Lessons exported</span>
                </div>
              </div>
            </div>
            <section>
              <div className="section-heading">
                <h2>
                  On your studio desk{" "}
                  <span className="muted-count">{projects.length}</span>
                </h2>
                <div className="search-box">
                  <Search size={17} />
                  <input
                    aria-label="Search presentations"
                    placeholder="Search presentations..."
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                  />
                </div>
              </div>
              <div className="filter-tabs">
                {["all", "review", "ready"].map((f) => (
                  <button
                    key={f}
                    aria-pressed={filter === f}
                    className={filter === f ? "active" : ""}
                    onClick={() => setFilter(f)}
                  >
                    {f === "all"
                      ? "All presentations"
                      : f === "review"
                        ? "In review"
                        : "Ready to export"}
                  </button>
                ))}
              </div>
              <div className="project-grid">
                {projects
                  .filter(
                    (p) =>
                      p.name.toLowerCase().includes(search.toLowerCase()) &&
                      (filter === "all" ||
                        (filter === "review"
                          ? p.approved_count < p.slide_count
                          : p.approved_count === p.slide_count)),
                  )
                  .map((p, i) => (
                    <button
                      className="project-card"
                      key={p.id}
                      onClick={() => void open(p.id)}
                    >
                      <div className={`project-cover cover-${i % 3}`}>
                        <span className="cover-category">{p.specialty}</span>
                        <BookOpen size={32} strokeWidth={1.2} />
                        <strong>{p.name}</strong>
                        <span className="cover-slides">
                          {p.slide_count} slides
                        </span>
                      </div>
                      <div className="project-info">
                        <div>
                          <h3>{p.name}</h3>
                          <span
                            className={`status ${p.approved_count === p.slide_count ? "ready" : ""}`}
                          >
                            {p.approved_count === p.slide_count
                              ? "Ready to export"
                              : "In review"}
                          </span>
                        </div>
                        <p>
                          {p.approved_count} of {p.slide_count} slides approved
                        </p>
                        <div className="progress-track">
                          <i
                            style={{
                              width: `${(p.approved_count / p.slide_count) * 100}%`,
                            }}
                          />
                        </div>
                        <footer>
                          <span>Edited {date(p.updated_at)}</span>
                          <ArrowRight size={17} />
                        </footer>
                      </div>
                    </button>
                  ))}
                <button
                  className="new-project-card"
                  onClick={() => setModal("import")}
                >
                  <span>
                    <Plus size={25} />
                  </span>
                  <strong>Your next production</strong>
                  <p>
                    Import a PowerPoint presentation
                    <br />
                    and bring the lesson to life.
                  </p>
                  <small>PPTX or PPTM · up to 150 MB</small>
                </button>
              </div>
              {search &&
                !projects.some((p) =>
                  p.name.toLowerCase().includes(search.toLowerCase()),
                ) && (
                  <p className="muted">No presentations match this search.</p>
                )}
            </section>
            <footer className="library-footer">
              <ShieldCheck size={16} />
              Your clinical content stays on this computer.
              <span>Narrate Studio · 0.1</span>
            </footer>
          </div>
        )}

        {page === "editor" && project && slide && (
          <div className="editor-page">
            <div className="editor-heading">
              <div>
                <button className="text-button" onClick={() => nav("library")}>
                  <ArrowLeft size={15} /> Presentations
                </button>
                <h1>{project.name}</h1>
              </div>
              <div className="editor-actions">
                <span className="review-count">
                  <CheckCheck size={17} />
                  {approved}/{project.slides.length} reviewed
                </span>
                <button
                  className="button secondary"
                  disabled={loading || busy(project) || dirty}
                  onClick={() => void action("/render")}
                >
                  <Film size={16} />
                  {project.slides.every((s) => s.image)
                    ? "Render again"
                    : "Render previews"}
                </button>
                <button
                  className="button primary"
                  disabled={loading || dirty || busy(project)}
                  onClick={() => setModal("export")}
                >
                  Export lesson <ArrowRight size={16} />
                </button>
              </div>
            </div>
            {project.job.status !== "idle" && (
              <div
                className={`job-strip ${project.job.status === "failed" ? "job-failed" : ""}`}
                role="status"
              >
                {busy(project) ? (
                  <LoaderCircle className="spin" size={17} />
                ) : project.job.status === "completed" ? (
                  <Check size={17} />
                ) : (
                  <AlertTriangle size={17} />
                )}
                <span>{project.job.message}</span>
                {busy(project) && (
                  <>
                    <progress
                      aria-label="Processing progress"
                      max="100"
                      value={project.job.progress}
                    />
                    <button
                      className="text-button"
                      onClick={() =>
                        void perform(async () => {
                          await post(`/projects/${project.id}/cancel`);
                        })
                      }
                    >
                      Cancel
                    </button>
                  </>
                )}
              </div>
            )}
            <div className="editor-grid">
              <aside className="slide-list">
                <div className="slide-list-heading">
                  SLIDES <span>{project.slides.length}</span>
                </div>
                {project.slides.map((s, i) => (
                  <button
                    aria-current={index === i ? "step" : undefined}
                    aria-label={`Slide ${s.number}: ${s.title}${s.approved ? ", approved" : ""}`}
                    key={s.number}
                    className={`slide-card ${index === i ? "current" : ""}`}
                    onClick={() => selectSlide(i)}
                  >
                    <div className="slide-thumb">
                      {s.image ? (
                        <img
                          loading="lazy"
                          src={`/api/projects/${project.id}/slides/${s.number}/image`}
                          alt={`Slide ${s.number}: ${s.title}`}
                        />
                      ) : (
                        <>
                          <FileText size={25} />
                          <span>Preview not rendered</span>
                        </>
                      )}
                      <span className="slide-number">
                        {String(s.number).padStart(2, "0")}
                      </span>
                      {s.approved && (
                        <span className="slide-approved">
                          <Check size={12} />
                        </span>
                      )}
                    </div>
                    <div className="slide-caption">
                      <span>{s.title}</span>
                      {s.flags.length > 0 && !s.approved && (
                        <span className="amber-dot" />
                      )}
                    </div>
                  </button>
                ))}
              </aside>
              <section className="preview-pane">
                <div className="preview-heading">
                  <span>SLIDE {String(slide.number).padStart(2, "0")}</span>
                  <span className="preview-badge">
                    <MonitorPlay size={13} /> Slide preview
                  </span>
                </div>
                <div className="slide-stage">
                  {slide.image ? (
                    <SlideVisual
                      key={`${project.id}:${slide.number}`}
                      src={`/api/projects/${project.id}/slides/${slide.number}/image`}
                      title={slide.title}
                      cues={visualCues}
                      placement={cuePlacement}
                      disabled={loading || busy(project)}
                      onSelect={(cueIndex) => {
                        setEditorTab("visual");
                        setCuePlacement(cueIndex);
                      }}
                      onPoint={(x, y) => {
                        if (cuePlacement === null || loading || busy(project))
                          return;
                        if (cuePlacement === -1) {
                          if (visualCues.length < 6)
                            setVisualCues([
                              ...visualCues,
                              { label: "", x, y, width: 0.24, height: 0.24 },
                            ]);
                        } else
                          setVisualCues(
                            visualCues.map((cue, cueIndex) =>
                              cueIndex === cuePlacement
                                ? { ...cue, x, y }
                                : cue,
                            ),
                          );
                        setCuePlacement(null);
                      }}
                    />
                  ) : (
                    <div className="preview-empty">
                      <Film size={40} strokeWidth={1} />
                      <h3>See the original slide</h3>
                      <p>
                        Render previews to inspect diagrams, tables,
                        <br />
                        and formatting before you approve narration.
                      </p>
                      <button
                        className="button secondary"
                        disabled={busy(project) || loading || dirty}
                        onClick={() => void action("/render")}
                      >
                        Render slide previews
                      </button>
                    </div>
                  )}
                </div>
                <div className="preview-controls">
                  <span>Original proportions preserved</span>
                  <div>
                    <button
                      className="icon-button"
                      aria-label="Previous slide"
                      disabled={index === 0}
                      onClick={() => selectSlide(index - 1)}
                    >
                      <ChevronLeft size={18} />
                    </button>
                    <span>
                      {index + 1} / {project.slides.length}
                    </span>
                    <button
                      className="icon-button"
                      aria-label="Next slide"
                      disabled={index === project.slides.length - 1}
                      onClick={() => selectSlide(index + 1)}
                    >
                      <ChevronRight size={18} />
                    </button>
                  </div>
                </div>
                <section
                  className="scene-timeline"
                  aria-label="Lesson scene sequence"
                >
                  <div className="scene-timeline-heading">
                    <Film size={14} />
                    <strong>Scene sequence</strong>
                    <span>
                      {approved} reviewed / {project.slides.length}
                    </span>
                  </div>
                  <div className="scene-track">
                    {project.slides.map((scene, sceneIndex) => (
                      <button
                        key={scene.number}
                        aria-current={index === sceneIndex ? "step" : undefined}
                        className={`scene-segment ${index === sceneIndex ? "active" : ""} ${scene.approved ? "reviewed" : ""}`}
                        onClick={() => selectSlide(sceneIndex)}
                        aria-label={`Open scene ${scene.number}: ${scene.title}`}
                      >
                        <span>{String(scene.number).padStart(2, "0")}</span>
                        <strong>{scene.title}</strong>
                        {scene.approved && <Check size={12} />}
                      </button>
                    ))}
                  </div>
                </section>
                <section className="source-panel">
                  <div className="source-heading">
                    <h3>
                      <BookOpen size={17} />
                      Source material
                    </h3>
                    <span>Reference while reviewing</span>
                  </div>
                  <div className="small-tabs">
                    {["text", "notes", "image", "tables", "references"].map(
                      (t) => (
                        <button
                          aria-pressed={sourceTab === t}
                          className={sourceTab === t ? "active" : ""}
                          onClick={() => setSourceTab(t)}
                          key={t}
                        >
                          {t === "text"
                            ? "Slide text"
                            : t === "notes"
                              ? "Speaker notes"
                              : t === "image"
                                ? "Image text"
                                : t[0].toUpperCase() + t.slice(1)}
                        </button>
                      ),
                    )}
                  </div>
                  <div
                    className={`source-content ${sourceTab === "image" ? "source-image-content" : ""}`}
                  >
                    {sourceTab === "image" && (
                      <fieldset
                        className="image-text-editor"
                        disabled={loading || busy(project)}
                      >
                        <legend className="sr-only">
                          Image text transcription
                        </legend>
                        <div className="image-text-heading">
                          <strong>Bring image text into the source.</strong>
                          <span>
                            {sourceDirty
                              ? "Unsaved changes"
                              : sourceReviewed
                                ? "Transcription checked"
                                : "Needs checking"}
                          </span>
                        </div>
                        <p>
                          Read the slide image with offline OCR, or type its
                          text below. OCR can misread medical terms, symbols,
                          units, and reading order. Check the transcription
                          against the original.
                        </p>
                        <button
                          type="button"
                          className="button secondary"
                          disabled={!health?.ocr || !slide.image || dirty}
                          onClick={() =>
                            void action(`/slides/${slide.number}/ocr`)
                          }
                        >
                          <FileText size={16} />
                          Read slide text offline
                        </button>
                        {!health?.ocr && (
                          <p className="image-text-hint">
                            Offline text recognition is unavailable. Check Setup
                            & preferences for runtime readiness; you can still
                            type the transcription here.
                          </p>
                        )}
                        {!slide.image && (
                          <p className="image-text-hint">
                            Render the slide preview before running text
                            recognition.
                          </p>
                        )}
                        {dirty && (
                          <p className="image-text-hint">
                            Save or discard your slide edits before reading the
                            image again.
                          </p>
                        )}
                        {slide.ocr && (
                          <p className="image-text-hint">
                            OCR engine: {slide.ocr.engine}. Extracted text
                            remains uncertain until you check it.
                          </p>
                        )}
                        {slide.ocr?.text && (
                          <details className="ocr-candidate">
                            <summary>Inspect detected text</summary>
                            <textarea
                              readOnly
                              value={slide.ocr.text}
                              aria-label="Detected OCR text"
                            />
                            <button
                              type="button"
                              className="button secondary"
                              onClick={() => {
                                setVisualText(slide.ocr?.text || "");
                                setSourceReviewed(false);
                              }}
                            >
                              Use detected text
                            </button>
                            <p className="image-text-hint">
                              Replaces the transcription below with this OCR
                              candidate. Check it again before saving your
                              review.
                            </p>
                          </details>
                        )}
                        <label>
                          Text visible in the slide image
                          <textarea
                            value={visualText}
                            onChange={(event) => {
                              setVisualText(event.target.value);
                              setSourceReviewed(false);
                            }}
                            placeholder="Transcribe the visible wording, including labels, units, and symbols. Add no unsupported interpretation."
                          />
                        </label>
                        <label className="checkbox-label">
                          <input
                            type="checkbox"
                            checked={sourceReviewed}
                            disabled={!visualText.trim()}
                            onChange={(event) =>
                              setSourceReviewed(event.target.checked)
                            }
                          />
                          I checked this transcription against the slide
                        </label>
                        <button
                          type="button"
                          className="button primary"
                          disabled={!sourceDirty}
                          onClick={() => void save()}
                        >
                          Save image text
                        </button>
                        <p className="image-text-hint">
                          Saving resets slide approval and preserves your other
                          pending slide edits. Checking the transcription does
                          not approve the clinical lesson.
                        </p>
                      </fieldset>
                    )}

                    {sourceTab === "text" &&
                      (slide.text ||
                        "No editable text was found. Open Image text to read the slide offline or transcribe its visible wording, then review the source before drafting.")}
                    {sourceTab === "notes" &&
                      (slide.notes || "This slide has no speaker notes.")}
                    {sourceTab === "tables" &&
                      (slide.tables.length
                        ? slide.tables.map((t, i) => (
                            <table key={i}>
                              <tbody>
                                {t.map((r, j) => (
                                  <tr key={j}>
                                    {r.map((c, k) => (
                                      <td key={k}>{c}</td>
                                    ))}
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          ))
                        : "No editable tables were found. Tables inside images require visual review.")}
                    {sourceTab === "references" &&
                      (slide.sources.length
                        ? slide.sources.map((s, i) => <p key={i}>{s}</p>)
                        : "No reference URLs were found in the speaker notes.")}
                  </div>
                </section>
              </section>
              <aside className="narration-pane">
                <div className="narration-title">
                  <span className="stat-icon mint">
                    <AudioLines size={19} />
                  </span>
                  <div>
                    <h2>Shape the lesson</h2>
                    <p>Your expertise, in every word.</p>
                  </div>
                </div>
                <div className="small-tabs editor-tabs">
                  <button
                    aria-pressed={editorTab === "narration"}
                    className={editorTab === "narration" ? "active" : ""}
                    onClick={() => setEditorTab("narration")}
                  >
                    Narration
                  </button>
                  <button
                    aria-pressed={editorTab === "check"}
                    className={editorTab === "check" ? "active" : ""}
                    onClick={() => setEditorTab("check")}
                  >
                    Knowledge check
                  </button>
                  <button
                    aria-pressed={editorTab === "visual"}
                    className={editorTab === "visual" ? "active" : ""}
                    onClick={() => setEditorTab("visual")}
                  >
                    Visual story
                  </button>
                </div>
                {editorTab === "narration" ? (
                  <>
                    <div className="script-label">
                      <label htmlFor="script">Narration script</label>
                      <span>
                        {dirty
                          ? "Unsaved changes"
                          : slide.approved
                            ? "Approved"
                            : "Draft"}
                      </span>
                    </div>
                    <textarea
                      id="script"
                      className="script-editor"
                      value={script}
                      onChange={(e) => setScript(e.target.value)}
                      placeholder="Write a concise explanation grounded in the slide and speaker notes."
                      disabled={loading || busy(project)}
                    />
                    <div className="script-meta">
                      <span>{narrationWordCount} words</span>
                      <span>
                        <Clock3 size={13} />~
                        {duration(narrationWordCount / 2.4)} estimated
                      </span>
                    </div>
                    <section
                      className="spoken-editing-guide"
                      aria-label="Spoken delivery editing guide"
                    >
                      <div>
                        <strong>
                          {narrationWordCount ? averageSentenceWords : "—"}
                        </strong>
                        <span>words per sentence, avg.</span>
                      </div>
                      <div>
                        <strong>{longSentenceCount}</strong>
                        <span>sentences over 26 words</span>
                      </div>
                      <div>
                        <strong>
                          {script.trim()
                            ? script
                                .trim()
                                .split(/\n\s*\n/)
                                .filter(Boolean).length
                            : 0}
                        </strong>
                        <span>paragraphs</span>
                      </div>
                      <p>
                        {longSentenceCount
                          ? "Try splitting long sentences into one idea per breath. Read the explanation aloud to check its flow."
                          : "Read the explanation aloud. Aim for one clear idea at a time."}{" "}
                        Counts are an editing guide; medical meaning still needs
                        your review.
                      </p>
                    </section>
                    <label className="narration-delivery-label">
                      Narration delivery
                      <select
                        value={narrationStyle}
                        disabled={loading || busy(project)}
                        onChange={(event) =>
                          setNarrationStyle(
                            event.target.value as "conversational" | "concise",
                          )
                        }
                      >
                        <option value="conversational">
                          Conversational teaching
                        </option>
                        <option value="concise">Concise explanation</option>
                      </select>
                    </label>
                    <p className="narration-delivery-help">
                      {narrationStyle === "conversational"
                        ? "A spoken explanation with a natural teaching flow and clear transitions."
                        : "A compact explanation that gets to the main point directly."}
                    </p>
                    <div className="draft-tools">
                      <button
                        className="button secondary"
                        disabled={
                          dirty || loading || busy(project) || !modelAvailable
                        }
                        aria-describedby={
                          drafting
                            ? "source-draft-help draft-progress"
                            : "source-draft-help"
                        }
                        aria-busy={drafting}
                        onClick={() =>
                          void action(`/slides/${slide.number}/draft`, {
                            model,
                            style: narrationStyle,
                            workflow: "agents",
                          })
                        }
                      >
                        {drafting ? (
                          <LoaderCircle size={15} className="spin" />
                        ) : (
                          <WandSparkles size={15} />
                        )}
                        {drafting
                          ? "Drafting & reviewing…"
                          : "Build teaching draft"}
                      </button>
                      <button
                        className="button primary compact"
                        disabled={!dirty || loading || busy(project)}
                        onClick={() => void save()}
                      >
                        Save
                      </button>
                    </div>
                    <div className="draft-workflow" aria-label="Draft workflow">
                      <span>Source analysis</span>
                      <ArrowRight size={12} />
                      <span>Teaching draft</span>
                      <ArrowRight size={12} />
                      <span>Critic review</span>
                    </div>
                    {drafting && (
                      <p
                        id="draft-progress"
                        className="draft-progress"
                        role="status"
                      >
                        Writing the draft and running source and editorial
                        checks locally. This can take several minutes. Review
                        the result against your source when it finishes.
                      </p>
                    )}
                    <p id="source-draft-help" className="source-draft-help">
                      Drafts use slide text, speaker notes, and image
                      transcription. Drafting and source/editorial checks may
                      take several minutes. A new draft replaces the saved
                      script and needs your fresh review.
                      {dirty && " Save or discard current edits first."}
                      {!modelAvailable &&
                        " Choose an installed local writing model in Setup & preferences to draft."}
                    </p>
                    <p className="origin">Source: {slide.draft_origin}</p>
                    <section
                      className="draft-preview-panel"
                      aria-label="Private slide preview"
                    >
                      <div className="draft-preview-heading">
                        <MonitorPlay size={20} />
                        <h3>Hear it. See it. Refine it.</h3>
                      </div>
                      <p>
                        Preview this saved slide with narration and guided
                        focus. Every frame is marked as an unapproved draft.
                      </p>
                      <details>
                        <summary>
                          Voice settings ·{" "}
                          {engine === "qwen" ? qwenVoice : voice} · {delivery}
                        </summary>
                        <VoiceControls
                          health={health}
                          engine={engine}
                          voice={engine === "qwen" ? qwenVoice : voice}
                          delivery={delivery}
                          rate={rate}
                          disabled={loading || busy(project)}
                          onEngine={(value) => {
                            engineChosen.current = true;
                            setEngine(value);
                          }}
                          onVoice={engine === "qwen" ? setQwenVoice : setVoice}
                          onDelivery={setDelivery}
                          onRate={setRate}
                        />
                      </details>
                      <button
                        className="button secondary"
                        disabled={
                          dirty ||
                          loading ||
                          busy(project) ||
                          !slide.image ||
                          !script.trim() ||
                          !voiceReady(health, engine) ||
                          !["qwen", "kokoro"].includes(engine)
                        }
                        onClick={() =>
                          void action(`/slides/${slide.number}/preview`, {
                            engine,
                            voice: engine === "qwen" ? qwenVoice : voice,
                            delivery,
                            rate,
                          })
                        }
                      >
                        <Play size={16} />
                        {busy(project) && project.job.kind === "preview"
                          ? "Rendering preview…"
                          : "Create slide preview"}
                      </button>
                      {dirty && (
                        <p className="muted">
                          Save your changes before generating a preview.
                        </p>
                      )}
                      {slide.draft_preview && (
                        <>
                          <p className="muted">
                            Revision {slide.draft_preview.revision} ·{" "}
                            {slide.draft_preview.voice} ·{" "}
                            {Math.round(slide.draft_preview.duration)} seconds
                            {slide.draft_preview.revision !== slide.revision
                              ? " · Older revision — regenerate after your changes."
                              : " · Private draft"}
                          </p>
                          <video
                            key={slide.draft_preview.url}
                            controls
                            preload="metadata"
                            src={slide.draft_preview.url}
                            aria-label={`Unapproved draft preview of slide ${slide.number}`}
                          />
                        </>
                      )}
                    </section>
                    <ScriptEvaluationPanel
                      slide={slide}
                      edited={sourceDirty || script !== slide.narration}
                      disabled={
                        dirty ||
                        loading ||
                        busy(project) ||
                        !modelAvailable ||
                        !script.trim()
                      }
                      evaluating={evaluating}
                      modelAvailable={modelAvailable}
                      dirty={dirty}
                      onEvaluate={() =>
                        void action(`/slides/${slide.number}/evaluate`, {
                          model,
                        })
                      }
                    />
                  </>
                ) : editorTab === "visual" ? (
                  <VisualStoryEditor
                    key={`${project.id}:${slide.number}`}
                    cues={visualCues}
                    paragraphs={script
                      .split(/\n\s*\n/)
                      .map((p) => p.trim())
                      .filter(Boolean)}
                    onChange={setVisualCues}
                    placement={cuePlacement}
                    onPlacement={setCuePlacement}
                    disabled={loading || busy(project)}
                    hasImage={slide.image}
                    dirty={dirty}
                    onSave={() => void save()}
                  />
                ) : (
                  <fieldset
                    className="knowledge-form"
                    disabled={loading || busy(project)}
                  >
                    <legend className="sr-only">Knowledge check</legend>
                    <p className="muted">
                      Optional. Add a question grounded in this slide. It
                      appears in the interactive lesson and requires review.
                    </p>
                    <label>
                      Question
                      <input
                        value={knowledge.question}
                        onChange={(e) =>
                          setKnowledge({
                            ...knowledge,
                            question: e.target.value,
                          })
                        }
                        placeholder="What should the learner understand?"
                      />
                    </label>
                    {knowledge.options.map((v, i) => (
                      <label key={i}>
                        Option {i + 1}
                        <div className="option-edit">
                          <input
                            type="radio"
                            name="correct"
                            aria-label={`Option ${i + 1} is correct`}
                            checked={knowledge.correct === i}
                            onChange={() =>
                              setKnowledge({ ...knowledge, correct: i })
                            }
                          />
                          <input
                            value={v}
                            onChange={(e) =>
                              setKnowledge({
                                ...knowledge,
                                options: knowledge.options.map((o, j) =>
                                  i === j ? e.target.value : o,
                                ),
                              })
                            }
                          />
                        </div>
                      </label>
                    ))}
                    <label>
                      Explanation
                      <textarea
                        value={knowledge.explanation}
                        onChange={(e) =>
                          setKnowledge({
                            ...knowledge,
                            explanation: e.target.value,
                          })
                        }
                        placeholder="Explain the answer using the source."
                      />
                    </label>
                    <small>Select the circle beside the correct answer.</small>
                    <button
                      className="button primary"
                      disabled={!dirty || loading || busy(project)}
                      onClick={() => void save()}
                    >
                      Save knowledge check
                    </button>
                  </fieldset>
                )}
                <div className="review-flags">
                  <h3>
                    <ShieldCheck size={16} />
                    Expert review
                  </h3>
                  {[...slide.flags, ...(slide.ai_flags || [])].length > 0 ? (
                    <ul>
                      {[...slide.flags, ...(slide.ai_flags || [])].map(
                        (f, i) => (
                          <li key={i}>{f}</li>
                        ),
                      )}
                    </ul>
                  ) : (
                    <p>
                      Verify accuracy, terminology, and the teaching sequence
                      against the source.
                    </p>
                  )}
                </div>
                <div
                  className={`approval-box ${slide.approved ? "is-approved" : ""}`}
                >
                  {slide.approved ? (
                    <>
                      <CheckCheck size={22} />
                      <strong>Approved by {slide.reviewer}</strong>
                      <p>
                        Revision {slide.revision}. Editing resets this approval.
                      </p>
                    </>
                  ) : (
                    <>
                      <label className="reviewer-label">
                        Reviewer name
                        <input
                          value={reviewer}
                          placeholder="Your name"
                          onChange={(e) => {
                            setReviewer(e.target.value);
                            localStorage.setItem(
                              "narrate-reviewer",
                              e.target.value,
                            );
                          }}
                        />
                      </label>
                      <label className="checkbox-label">
                        <input
                          type="checkbox"
                          checked={ack}
                          onChange={(e) => setAck(e.target.checked)}
                        />
                        <span>
                          I checked the visual, medical claims, quantities,
                          narration, visual cue labels and source regions, and
                          any knowledge check.
                        </span>
                      </label>
                      <button
                        className="button primary full"
                        disabled={
                          !ack ||
                          reviewer.trim().length < 2 ||
                          dirty ||
                          !slide.image ||
                          !script.trim() ||
                          (!!visualText.trim() && !sourceReviewed) ||
                          busy(project) ||
                          loading
                        }
                        onClick={() =>
                          void action(`/slides/${slide.number}/approve`, {
                            revision: slide.revision,
                            reviewer,
                            acknowledged: ack,
                          })
                        }
                      >
                        <Check size={16} />
                        Approve this slide
                      </button>
                      {!!visualText.trim() && !sourceReviewed && (
                        <small>
                          Open Image text and check the transcription against
                          the slide before approving.
                        </small>
                      )}
                      <small>
                        Full lesson export unlocks after approval. Private draft
                        previews are available above.
                      </small>
                    </>
                  )}
                </div>
              </aside>
            </div>
          </div>
        )}

        {page === "exports" && project && (
          <div className="page">
            <div className="page-heading">
              <div>
                <div className="eyebrow">READY FOR YOUR LEARNERS</div>
                <h1>Lesson exports</h1>
                <p>{project.name}</p>
              </div>
              <button
                className="button primary"
                disabled={busy(project)}
                onClick={() => setModal("export")}
              >
                <Plus size={17} />
                Create export
              </button>
            </div>
            {!activeExports.length ? (
              <div className="empty-state">
                <MonitorPlay size={45} />
                <h2>Your lesson is taking shape.</h2>
                <p>
                  Review and approve a slide range, then create your first
                  export.
                </p>
                <button
                  className="button secondary"
                  onClick={() => nav("editor")}
                >
                  Return to editor
                </button>
              </div>
            ) : (
              activeExports
                .slice()
                .reverse()
                .map((e) => (
                  <section className="export-card" key={e.id}>
                    <div className="export-card-title">
                      <div>
                        <h2>
                          Slides {e.settings.start}–{e.settings.end}
                        </h2>
                        <p>
                          {date(e.created_at)} · {duration(e.duration)} · 1080p
                        </p>
                      </div>
                      <span className="status ready">Complete</span>
                    </div>
                    <ExportVideo
                      src={`/api/projects/${project.id}/exports/${e.id}/presentation.mp4`}
                      label={`Lesson video, slides ${e.settings.start} to ${e.settings.end}`}
                    />
                    <div className="export-links">
                      {[
                        ["interactive-lesson.zip", "Interactive lesson"],
                        ["presentation.mp4", "MP4 video"],
                        ["captions.srt", "Captions"],
                        ["transcript.txt", "Transcript"],
                        ["manifest.json", "Review record"],
                      ].map(([file, label]) => (
                        <a
                          className="button secondary"
                          key={file}
                          href={`/api/projects/${project.id}/exports/${e.id}/${file}`}
                          download={file}
                        >
                          <ArrowDownToLine size={15} />
                          {label}
                        </a>
                      ))}
                    </div>
                    <p className="muted">
                      For interaction, extract the lesson ZIP and open
                      index.html. Keep its video file in the same folder.
                    </p>
                  </section>
                ))
            )}
          </div>
        )}

        {page === "setup" && (
          <div className="page setup-page">
            <div className="page-heading">
              <div>
                <div className="eyebrow">MADE TO WORK ON YOUR DEVICE</div>
                <h1>Your local studio</h1>
                <p>
                  Check the tools behind your lessons and set your preferences.
                </p>
              </div>
              <button
                className="button secondary"
                onClick={() => void perform(loadHealth)}
              >
                Refresh status
              </button>
            </div>
            <div className="settings-grid">
              <section className="settings-card">
                <h2>
                  <ShieldCheck size={20} />
                  Runtime readiness
                </h2>
                {[
                  [
                    health?.renderer,
                    "Slide rendering",
                    health?.renderer_name || "Checking renderer",
                  ],
                  [health?.ffmpeg, "Video assembly", "FFmpeg · 1080p H.264"],
                  [
                    health?.qwen_tts,
                    "Expressive voice delivery",
                    "Qwen · local Aiden and Ryan voices",
                  ],
                  [
                    health?.ocr,
                    "Image text recognition",
                    "Offline OCR · review extracted text before use",
                  ],
                  [
                    !!health?.models.length,
                    "Local narration AI",
                    health?.models.join(", ") ||
                      "Start Ollama and install a local model",
                  ],
                  [
                    health?.kokoro,
                    "Expressive voice",
                    "Kokoro · four narrator voices",
                  ],
                  [health?.piper, "Compact voice", "Piper · English Lessac"],
                ].map(([ok, title, desc], i) => (
                  <div className="runtime-row" key={i}>
                    <span className={`runtime-icon ${ok ? "ok" : "warn"}`}>
                      {ok ? <Check size={16} /> : <AlertTriangle size={16} />}
                    </span>
                    <div>
                      <strong>{title}</strong>
                      <p>{desc}</p>
                    </div>
                    <span>{ok ? "Ready" : "Setup needed"}</span>
                  </div>
                ))}
                <p className="muted">
                  Models are installed during setup. The app never downloads
                  them during processing.
                </p>
              </section>
              <section className="settings-card">
                <h2>
                  <Settings2 size={20} />
                  Lesson preferences
                </h2>
                <label>
                  Local writing model
                  <select
                    value={model}
                    aria-describedby="writing-model-help"
                    onChange={(e) => {
                      modelChosen.current = true;
                      setModel(e.target.value);
                    }}
                  >
                    {model && !modelAvailable && (
                      <option value={model} disabled>
                        {model} (not installed)
                      </option>
                    )}
                    {health?.models.length ? (
                      health.models.map((m) => <option key={m}>{m}</option>)
                    ) : (
                      <option value="">No local models available</option>
                    )}
                  </select>
                </label>
                <p id="writing-model-help" className="writing-model-help">
                  Choose an installed local model for writing and reviewing the
                  script. Qwen3.5:9b is the higher-capacity option tested on
                  this workstation. The separate voice engine controls how the
                  script sounds.
                </p>
                <VoiceControls
                  health={health}
                  engine={engine}
                  voice={engine === "qwen" ? qwenVoice : voice}
                  delivery={delivery}
                  rate={rate}
                  disabled={loading || busy(project)}
                  onEngine={(value) => {
                    engineChosen.current = true;
                    setEngine(value);
                  }}
                  onVoice={engine === "qwen" ? setQwenVoice : setVoice}
                  onDelivery={setDelivery}
                  onRate={setRate}
                />
                <label>
                  Reviewer name
                  <input
                    value={reviewer}
                    onChange={(e) => {
                      setReviewer(e.target.value);
                      localStorage.setItem("narrate-reviewer", e.target.value);
                    }}
                  />
                </label>
                <p className="muted">
                  Model and voice preferences apply during this session.
                </p>
              </section>
              <section className="settings-card">
                <h2>
                  <LockKeyhole size={20} />
                  Storage & privacy
                </h2>
                <p>
                  Presentations, model output, audio, and review records remain
                  on this computer. The backend contacts only the local Ollama
                  service.
                </p>
                <label>
                  Workspace data<code>{health?.data_path}</code>
                </label>
                <p className="muted">
                  Back up this folder with the app stopped. No telemetry, cloud
                  APIs, or remote fonts are used.
                </p>
              </section>
              {project && (
                <section className="settings-card">
                  <h2>
                    <BookOpen size={20} />
                    Current presentation
                  </h2>
                  <ProjectSettings
                    key={project.id}
                    project={project}
                    onSave={(p) => setProject(p)}
                    onError={setError}
                  />
                  <a
                    className="text-button"
                    href={`/api/projects/${project.id}/review.json`}
                    download
                  >
                    <ArrowDownToLine size={16} />
                    Download full review record
                  </a>
                </section>
              )}
            </div>
          </div>
        )}
      </main>
      {modal && (
        <div
          className="modal-backdrop"
          onClick={() => !loading && setModal("")}
        >
          <section
            ref={dialogRef}
            tabIndex={-1}
            className="modal"
            role="dialog"
            aria-busy={loading}
            aria-modal="true"
            aria-label={
              modal === "import"
                ? "Import presentation"
                : modal === "export"
                  ? "Export lesson"
                  : "Quick guide"
            }
            onClick={(e) => e.stopPropagation()}
          >
            <button
              className="modal-close icon-button"
              aria-label="Close dialog"
              disabled={loading}
              onClick={() => setModal("")}
            >
              <X size={21} />
            </button>
            {error && (
              <div className="error-banner modal-error" role="alert">
                <AlertTriangle size={18} />
                <span>{error}</span>
                <button
                  className="icon-button"
                  aria-label="Dismiss error"
                  onClick={() => setError("")}
                >
                  <X size={16} />
                </button>
              </div>
            )}
            {modal === "import" && (
              <>
                <span className="modal-icon">
                  <Upload size={25} />
                </span>
                <h2>Start with your presentation.</h2>
                <p>Bring your expertise. We’ll help you shape the lesson.</p>
                <div
                  className={`drop-zone ${drag ? "dragging" : ""}`}
                  onDragOver={(e) => {
                    e.preventDefault();
                    setDrag(true);
                  }}
                  onDragLeave={() => setDrag(false)}
                  onDrop={(e) => {
                    e.preventDefault();
                    setDrag(false);
                    void upload(e.dataTransfer.files[0]);
                  }}
                >
                  <Upload size={35} strokeWidth={1.2} />
                  <h3>Drop your PowerPoint here</h3>
                  <p>PPTX or PPTM · up to 150 MB · up to 500 slides</p>
                  <button
                    className="button primary"
                    disabled={loading}
                    onClick={() => fileInput.current?.click()}
                  >
                    {loading ? (
                      <LoaderCircle size={17} className="spin" />
                    ) : (
                      <FolderOpen size={17} />
                    )}
                    Choose a file
                  </button>
                  <input
                    type="file"
                    hidden
                    ref={fileInput}
                    accept=".pptx,.pptm"
                    onChange={(e) => {
                      const file = e.target.files?.[0];
                      e.target.value = "";
                      void upload(file);
                    }}
                  />
                </div>
                <div className="import-note">
                  <ShieldCheck size={18} />
                  <p>
                    Files stay on your device. Macros and active embedded
                    content are removed from the rendering copy.
                  </p>
                </div>
              </>
            )}
            {modal === "export" && project && (
              <>
                <span className="modal-icon">
                  <MonitorPlay size={25} />
                </span>
                <h2>Make it a lesson.</h2>
                <p>
                  Create an interactive learning package and a captioned MP4.
                </p>
                <fieldset
                  className="output-style-selector"
                  disabled={loading || busy(project)}
                >
                  <legend>Visual direction</legend>
                  <div className="output-style-options">
                    <label
                      className={`output-style-option ${visualStyle === "focus" ? "selected" : ""}`}
                    >
                      <input
                        type="radio"
                        name="visual-style"
                        value="focus"
                        checked={visualStyle === "focus"}
                        onChange={() => setVisualStyle("focus")}
                      />
                      <span
                        className="style-mini-preview studio-mini"
                        aria-hidden="true"
                      >
                        <i />
                        <i />
                        <i />
                      </span>
                      <strong>Guided focus</strong>
                      <span>
                        Move into each authored detail, pause to explain it,
                        then return to the whole slide.
                      </span>
                    </label>
                    <label
                      className={`output-style-option ${visualStyle === "whiteboard" ? "selected" : ""}`}
                    >
                      <input
                        type="radio"
                        name="visual-style"
                        value="whiteboard"
                        checked={visualStyle === "whiteboard"}
                        onChange={() => setVisualStyle("whiteboard")}
                      />
                      <span
                        className="style-mini-preview whiteboard-mini"
                        aria-hidden="true"
                      >
                        <i />
                        <i />
                        <i />
                      </span>
                      <strong>Whiteboard</strong>
                      <span>
                        Reveal authored source regions in sequence, then show
                        the complete slide.
                      </span>
                    </label>
                    <label
                      className={`output-style-option ${visualStyle === "studio" ? "selected" : ""}`}
                    >
                      <input
                        type="radio"
                        name="visual-style"
                        value="studio"
                        checked={visualStyle === "studio"}
                        onChange={() => setVisualStyle("studio")}
                      />
                      <span
                        className="style-mini-preview studio-mini"
                        aria-hidden="true"
                      >
                        <i />
                        <i />
                        <i />
                      </span>
                      <strong>Studio</strong>
                      <span>
                        Present the full slide with cinematic framing and timed
                        callouts.
                      </span>
                    </label>
                  </div>
                  <p className="muted">
                    Source styles use your reviewed source visuals. Cues follow
                    your paragraph assignments in Guided focus and Whiteboard,
                    or use automatic spacing. Review their timing by playing the
                    exported video.
                  </p>
                </fieldset>
                {health?.powerpoint_animation && (
                  <label className="native-animation-choice">
                    <input
                      type="radio"
                      name="visual-style"
                      value="powerpoint"
                      checked={visualStyle === "powerpoint"}
                      onChange={() => setVisualStyle("powerpoint")}
                      disabled={loading || busy(project)}
                    />
                    <span>
                      <strong>Use the deck’s PowerPoint effects</strong>
                      <br />
                      Existing animations play automatically and their complete
                      timeline fits the narration. Slides without effects stay
                      static. Shape-triggered effects and embedded media require
                      editing in PowerPoint.
                    </span>
                  </label>
                )}
                <div className="range-fields">
                  <label>
                    First slide
                    <input
                      type="number"
                      min="1"
                      max={project.slides.length}
                      value={rangeStart}
                      onChange={(e) => setRangeStart(Number(e.target.value))}
                    />
                  </label>
                  <label>
                    Last slide
                    <input
                      type="number"
                      min={rangeStart}
                      max={project.slides.length}
                      value={rangeEnd}
                      onChange={(e) => setRangeEnd(Number(e.target.value))}
                    />
                  </label>
                </div>
                {Number.isInteger(rangeStart) &&
                  Number.isInteger(rangeEnd) &&
                  rangeEnd >= rangeStart &&
                  rangeStart > 0 &&
                  rangeEnd <= project.slides.length && (
                    <p className="export-cue-coverage">
                      {
                        project.slides.filter(
                          (s) =>
                            s.number >= rangeStart &&
                            s.number <= rangeEnd &&
                            s.visual_cues?.length,
                        ).length
                      }{" "}
                      of {rangeEnd - rangeStart + 1} selected slides have
                      authored visual cues. Slides without cues retain their
                      full source visual.
                    </p>
                  )}
                <VoiceControls
                  health={health}
                  engine={engine}
                  voice={engine === "qwen" ? qwenVoice : voice}
                  delivery={delivery}
                  rate={rate}
                  disabled={loading || busy(project)}
                  onEngine={(value) => {
                    engineChosen.current = true;
                    setEngine(value);
                  }}
                  onVoice={engine === "qwen" ? setQwenVoice : setVoice}
                  onDelivery={setDelivery}
                  onRate={setRate}
                />
                <label className="checkbox-label">
                  <input
                    type="checkbox"
                    checked={burn}
                    onChange={(e) => setBurn(e.target.checked)}
                  />
                  Show permanent captions in the video
                </label>
                <div className="export-summary">
                  <Check size={17} />
                  1080p video · interactive chapters · transcript · knowledge
                  checks
                </div>
                <p className="muted" aria-live="polite">
                  {!Number.isInteger(rangeStart) ||
                  !Number.isInteger(rangeEnd) ||
                  rangeStart < 1 ||
                  rangeEnd > project.slides.length ||
                  rangeEnd < rangeStart
                    ? `Choose a valid slide range from 1 to ${project.slides.length}.`
                    : `${project.slides.filter((s) => s.number >= rangeStart && s.number <= rangeEnd && !s.approved).length} slides in this range still need approval.`}
                </p>
                {(!health?.ffmpeg || !voiceReady(health, engine)) && (
                  <p className="muted">
                    Export requires FFmpeg and an available voice engine. Check
                    Setup & preferences for runtime readiness.
                  </p>
                )}
                <button
                  className="button primary full"
                  disabled={
                    busy(project) ||
                    loading ||
                    dirty ||
                    !Number.isInteger(rangeStart) ||
                    !Number.isInteger(rangeEnd) ||
                    !voiceReady(health, engine) ||
                    !health?.ffmpeg ||
                    rangeStart < 1 ||
                    rangeEnd > project.slides.length ||
                    rangeEnd < rangeStart ||
                    project.slides.some(
                      (s) =>
                        s.number >= rangeStart &&
                        s.number <= rangeEnd &&
                        !s.approved,
                    )
                  }
                  onClick={() =>
                    void perform(async () => {
                      setProject(
                        await post<Project>(`/projects/${project.id}/export`, {
                          start: rangeStart,
                          end: rangeEnd,
                          engine,
                          voice: engine === "qwen" ? qwenVoice : voice,
                          delivery,
                          rate,
                          burn_captions: burn,
                          visual_style: visualStyle,
                        }),
                      );
                      setModal("");
                      setPage("editor");
                    })
                  }
                >
                  <MonitorPlay size={17} />
                  Create lesson
                </button>
              </>
            )}
            {modal === "guide" && (
              <>
                <span className="modal-icon">
                  <BookOpen size={25} />
                </span>
                <h2>A clear path to a better lesson.</h2>
                <ol className="guide-steps">
                  <li>
                    <strong>Import & inspect</strong>
                    <p>
                      Upload any PPTX or PPTM. Render previews, then inspect the
                      original visuals beside extracted text and notes.
                    </p>
                  </li>
                  <li>
                    <strong>Shape the explanation</strong>
                    <p>
                      Write narration or draft with local AI. Check medical
                      claims, doses, units, abbreviations, and the teaching
                      sequence.
                    </p>
                  </li>
                  <li>
                    <strong>Add a learning moment</strong>
                    <p>
                      Add an optional knowledge check with an explanation
                      grounded in your source.
                    </p>
                  </li>
                  <li>
                    <strong>Review & share</strong>
                    <p>
                      Approve each slide by name. Export the selected range as a
                      video and an interactive lesson that opens offline.
                    </p>
                  </li>
                </ol>
                <div className="import-note">
                  <ShieldCheck size={18} />
                  <p>
                    Automated flags help focus review. They do not establish
                    clinical correctness. Static slide rendering does not
                    preserve PowerPoint animations.
                  </p>
                </div>
              </>
            )}
          </section>
        </div>
      )}
    </div>
  );
}
function EvaluationEvidence({
  finding,
  report,
}: {
  finding: EvaluationFinding;
  report: ScriptEvaluation;
}) {
  function passages(kind: "source" | "draft"): EvidencePassage[] {
    const supplied =
      kind === "source" ? finding.source_spans : finding.draft_spans;
    const ids = [
      ...((kind === "source" ? finding.source_ids : finding.draft_ids) || []),
      ...((kind === "source"
        ? finding.verification_source_ids
        : finding.verification_draft_ids) || []),
    ];
    const collection =
      kind === "source"
        ? report.evidence_audit?.source_passages
        : report.evidence_audit?.draft_passages;
    const found = [...(supplied || [])];
    for (const id of ids) {
      if (found.some((item) => item.id === id)) continue;
      const value = Array.isArray(collection)
        ? collection.find((item) => item.id === id)
        : collection?.[id];
      found.push(
        typeof value === "string"
          ? { id, text: value }
          : value || {
              id,
              text: "Linked passage unavailable in this report. Re-evaluate to retrieve its evidence.",
            },
      );
    }
    return found;
  }
  return (
    <div className="finding-evidence">
      {finding.verification_reason && (
        <div>
          <h4>Challenge review reasoning</h4>
          <p>{finding.verification_reason}</p>
        </div>
      )}
      {(["source", "draft"] as const).map((kind) => {
        const spans = passages(kind);
        const quote =
          kind === "source" ? finding.source_quote : finding.draft_quote;
        return spans.length || quote ? (
          <div key={kind}>
            <h4>
              {kind === "source"
                ? "Exact source passages"
                : "Exact script passages"}
            </h4>
            {spans.length ? (
              spans.map((span, index) => (
                <div className="evidence-passage" key={`${span.id}-${index}`}>
                  <span className="evidence-id">{span.id}</span>
                  <blockquote>{span.text}</blockquote>
                </div>
              ))
            ) : (
              <blockquote>{quote}</blockquote>
            )}
          </div>
        ) : null;
      })}
      {finding.remediation && (
        <div>
          <h4>Suggested next edit — check against the evidence</h4>
          <p>{finding.remediation}</p>
        </div>
      )}
    </div>
  );
}

function ScriptEvaluationPanel({
  slide,
  edited,
  disabled,
  evaluating,
  modelAvailable,
  dirty,
  onEvaluate,
}: {
  slide: Slide;
  edited: boolean;
  disabled: boolean;
  evaluating: boolean;
  modelAvailable: boolean;
  dirty: boolean;
  onEvaluate: () => void;
}) {
  const report = slide.evaluation;
  const findings = report?.findings || [];
  const uncertain = report?.uncertain_findings || [];
  const dismissed = report?.dismissed_findings || [];
  const hints = report?.review_hints || [];
  const obsolete =
    !!report && report.version !== "local-evaluation-v2-evidence-addressed";
  const changed =
    !!report &&
    (edited ||
      (report.assessed_revision !== undefined &&
        report.assessed_revision !== slide.revision));
  const outdated = obsolete || changed || !!report?.stale;
  const label = evaluating
    ? "Evaluating saved script"
    : slide.evaluation_error
      ? "Latest assessment failed"
      : obsolete
        ? "Obsolete assessment — re-evaluate"
        : changed || report?.stale
          ? "Assessment out of date"
          : !report
            ? "Not assessed"
            : findings.length || uncertain.length
              ? "Findings and uncertainty require review"
              : "Practitioner review needed";
  const categoryNames: Record<string, string> = {
    quantity: "Quantities and units",
    qualifier: "Conditions and qualifiers",
    source_fidelity: "Source fidelity",
    source_conflict: "Conflicting source details",
    readability: "Spoken clarity",
  };
  return (
    <section
      className="script-evaluation"
      aria-label="Source fidelity evaluation"
      aria-busy={evaluating}
    >
      <div className="evaluation-heading">
        <FileText size={18} />
        <h3>Check source fidelity</h3>
      </div>
      <p className="evaluation-state" role="status">
        {evaluating && <LoaderCircle size={14} className="spin" />}
        {label}
      </p>
      <p>
        Compare the saved script with exact source passages. Two model passes
        can still miss errors or agree incorrectly. Full medical review remains
        necessary; this assessment does not approve content or authorize
        automatic rewriting.
      </p>
      <button
        type="button"
        className="button secondary full"
        disabled={disabled}
        onClick={onEvaluate}
      >
        {evaluating
          ? "Evaluating…"
          : obsolete
            ? "Re-evaluate saved script"
            : "Evaluate saved script"}
      </button>
      {dirty && (
        <p className="evaluation-hint">
          Save your edits before evaluating. Existing findings describe the
          previously saved script and source.
        </p>
      )}
      {!modelAvailable && (
        <p className="evaluation-hint">
          Choose an installed local writing model in Setup & preferences.
        </p>
      )}
      {evaluating && (
        <p className="evaluation-hint">
          The local reviewers compare source and script evidence. This may take
          several minutes. Your narration stays unchanged.
        </p>
      )}
      {!!slide.evaluation_error && (
        <p className="evaluation-error" role="alert">
          {slide.evaluation_error}
          {report && " The previous assessment remains below."}
        </p>
      )}
      {obsolete && (
        <p className="evaluation-stale">
          This report uses an older assessment method. Its findings are
          historical, not an assessment under the current evidence review
          protocol. Re-evaluate the saved script.
        </p>
      )}
      {changed && (
        <p className="evaluation-stale">
          These findings do not assess the current edits. Save and evaluate
          again before relying on them.
        </p>
      )}
      {report?.stale && (
        <div className="evaluation-stale" role="status">
          <p>This saved assessment needs to be run again.</p>
          <ul>
            {(report.stale_reasons?.length
              ? report.stale_reasons
              : [
                  "The assessment no longer matches the current source or reviewer settings.",
                ]
            ).map((reason, index) => (
              <li key={index}>{reason}</li>
            ))}
          </ul>
        </div>
      )}
      {report && (
        <div
          className={
            outdated ? "evaluation-report is-stale" : "evaluation-report"
          }
        >
          <div className="evaluation-meta">
            {report.model && <span>Local model: {report.model}</span>}
            {report.model_identity?.digest && (
              <span>Recorded model digest: {report.model_identity.digest}</span>
            )}
            {report.audience && (
              <span>Assessed audience: {report.audience}</span>
            )}
            {report.assessed_revision !== undefined && (
              <span>Saved revision {report.assessed_revision}</span>
            )}
            <span>
              {obsolete
                ? "Historical assessment"
                : "Source alignment + challenge review · no automatic script changes"}
            </span>
          </div>
          {report.summary && (
            <p className="evaluation-summary">{report.summary}</p>
          )}
          <section
            className="evaluation-group"
            aria-label="Reported discrepancies"
          >
            <h4>
              {obsolete ? "Historical findings" : "Reported discrepancies"}{" "}
              <span>{findings.length}</span>
            </h4>
            {!!findings.length && (
              <p>
                Inspect every linked passage, including both sides of a source
                conflict, before deciding whether to edit.
              </p>
            )}
            <ol className="evaluation-findings">
              {findings.map((finding, index) => (
                <li key={finding.id || index}>
                  <details>
                    <summary>
                      <span
                        className={`finding-severity ${finding.severity === "high" ? "high" : ""}`}
                      >
                        {finding.severity === "high"
                          ? "High priority"
                          : "Requires review"}
                      </span>
                      <strong>
                        {categoryNames[
                          finding.category || finding.type || ""
                        ] || "Source review"}
                      </strong>
                      <span>{finding.message || finding.reason}</span>
                    </summary>
                    <div className="finding-evidence">
                      <span className="finding-origin">
                        {obsolete
                          ? "Historical automated finding"
                          : finding.origin === "critic"
                            ? "Two-pass model agreement · requires review"
                            : "Source status notice · requires review"}
                      </span>
                    </div>
                    <EvaluationEvidence finding={finding} report={report} />
                  </details>
                </li>
              ))}
            </ol>
            {!findings.length && (
              <p>
                No discrepancies were retained. This does not establish source
                fidelity or clinical correctness; review all claims, quantities,
                and qualifiers.
              </p>
            )}
          </section>
          {!!uncertain.length && (
            <section
              className="evaluation-group evaluation-uncertain"
              aria-label="Unresolved assessment uncertainty"
            >
              <h4>
                Unresolved uncertainty <span>{uncertain.length}</span>
              </h4>
              <p>
                The model checks did not establish an outcome for these items.
                Review the evidence yourself; uncertainty is not a clean result.
              </p>
              <ol className="evaluation-findings">
                {uncertain.map((finding, index) => (
                  <li key={finding.id || index}>
                    <details>
                      <summary>
                        <strong>
                          {categoryNames[
                            finding.type || finding.category || ""
                          ] || "Unresolved source question"}
                        </strong>
                        <span>{finding.reason || finding.message}</span>
                      </summary>
                      <EvaluationEvidence finding={finding} report={report} />
                    </details>
                  </li>
                ))}
              </ol>
            </section>
          )}
          {!!hints.length && (
            <section className="evaluation-group" aria-label="Editing hints">
              <h4>
                Editing hints <span>{hints.length}</span>
              </h4>
              <p>
                Lexical and readability checks suggest places to inspect. These
                are not confirmed factual errors.
              </p>
              <ol className="evaluation-findings">
                {hints.map((hint, index) => (
                  <li key={index}>
                    {typeof hint === "string" ? (
                      <p className="evaluation-hint-item">{hint}</p>
                    ) : (
                      <details>
                        <summary>
                          <strong>
                            {categoryNames[hint.category || hint.type || ""] ||
                              "Editing guide"}
                          </strong>
                          <span>{hint.message || hint.reason}</span>
                        </summary>
                        <EvaluationEvidence finding={hint} report={report} />
                      </details>
                    )}
                  </li>
                ))}
              </ol>
            </section>
          )}
          {!!dismissed.length && (
            <details className="evaluation-group evaluation-dismissed">
              <summary>Refuted candidates · {dismissed.length}</summary>
              <p>
                A later model pass rejected these proposed discrepancies. This
                is a model judgment, not proof that the passages are correct.
              </p>
              <ol className="evaluation-findings">
                {dismissed.map((finding, index) => (
                  <li key={finding.id || index}>
                    <details>
                      <summary>
                        <strong>
                          {categoryNames[
                            finding.type || finding.category || ""
                          ] || "Refuted candidate"}
                        </strong>
                        <span>{finding.reason || finding.message}</span>
                      </summary>
                      <EvaluationEvidence finding={finding} report={report} />
                    </details>
                  </li>
                ))}
              </ol>
            </details>
          )}
        </div>
      )}
    </section>
  );
}

function ExportVideo({ src, label }: { src: string; label: string }) {
  const video = useRef<HTMLVideoElement>(null);
  const [failed, setFailed] = useState(false);
  return (
    <div className="export-video-player">
      <video
        ref={video}
        controls
        preload="metadata"
        src={src}
        aria-label={label}
        onError={() => setFailed(true)}
        onLoadedMetadata={() => setFailed(false)}
      />
      {failed && (
        <div className="export-playback-error" role="alert">
          <AlertTriangle size={18} />
          <div>
            <strong>Video preview could not load.</strong>
            <p>
              Check that the local studio is running, then retry. If the export
              was moved or deleted, create it again.
            </p>
          </div>
          <button
            type="button"
            className="button secondary"
            onClick={() => {
              setFailed(false);
              video.current?.load();
            }}
          >
            Retry preview
          </button>
        </div>
      )}
    </div>
  );
}

function SlideVisual({
  src,
  title,
  cues,
  placement,
  disabled,
  onSelect,
  onPoint,
}: {
  src: string;
  title: string;
  cues: VisualCue[];
  placement: number | null;
  disabled: boolean;
  onSelect: (index: number) => void;
  onPoint: (x: number, y: number) => void;
}) {
  const stage = useRef<HTMLDivElement>(null),
    image = useRef<HTMLImageElement>(null);
  const [bounds, setBounds] = useState<{
    left: number;
    top: number;
    width: number;
    height: number;
  } | null>(null);
  const measure = () => {
    const root = stage.current,
      img = image.current;
    if (!root || !img?.naturalWidth || !root.clientWidth || !root.clientHeight)
      return;
    const scale = Math.min(
      root.clientWidth / img.naturalWidth,
      root.clientHeight / img.naturalHeight,
    );
    const width = img.naturalWidth * scale,
      height = img.naturalHeight * scale;
    setBounds({
      left: (root.clientWidth - width) / 2,
      top: (root.clientHeight - height) / 2,
      width,
      height,
    });
  };
  useEffect(() => {
    const observer = new ResizeObserver(measure);
    if (stage.current) observer.observe(stage.current);
    measure();
    return () => observer.disconnect();
  }, [src]);
  return (
    <div className="cue-stage-content" ref={stage}>
      <img ref={image} src={src} alt={title} onLoad={measure} />
      {bounds && (
        <div
          className={`cue-image-overlay ${placement !== null && !disabled ? "is-placing" : ""}`}
          style={bounds}
          onClick={(event) => {
            if (placement === null || disabled) return;
            const rect = event.currentTarget.getBoundingClientRect();
            onPoint(
              Math.max(
                0,
                Math.min(1, (event.clientX - rect.left) / rect.width),
              ),
              Math.max(
                0,
                Math.min(1, (event.clientY - rect.top) / rect.height),
              ),
            );
          }}
        >
          {cues.map((cue, index) => {
            const left = Math.max(0, cue.x - (cue.width ?? 0.24) / 2),
              top = Math.max(0, cue.y - (cue.height ?? 0.24) / 2),
              right = Math.min(1, cue.x + (cue.width ?? 0.24) / 2),
              bottom = Math.min(1, cue.y + (cue.height ?? 0.24) / 2);
            return (
              <div
                key={`region-${index}`}
                className={`visual-cue-region ${placement === index ? "selected" : ""}`}
                aria-hidden="true"
                style={{
                  left: `${left * 100}%`,
                  top: `${top * 100}%`,
                  width: `${(right - left) * 100}%`,
                  height: `${(bottom - top) * 100}%`,
                }}
              >
                <span>{index + 1}</span>
              </div>
            );
          })}
          {cues.map((cue, index) => (
            <button
              type="button"
              key={index}
              className={`visual-cue-marker ${placement === index ? "selected" : ""}`}
              disabled={disabled}
              style={{ left: `${cue.x * 100}%`, top: `${cue.y * 100}%` }}
              title={`${index + 1}. ${cue.label || "Add a label"}`}
              aria-label={`Position cue ${index + 1}: ${cue.label || "unlabeled"}`}
              onClick={(event) => {
                event.stopPropagation();
                onSelect(index);
              }}
            >
              <span>{index + 1}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function VisualStoryEditor({
  cues,
  paragraphs,
  onChange,
  placement,
  onPlacement,
  disabled,
  hasImage,
  dirty,
  onSave,
}: {
  cues: VisualCue[];
  paragraphs: string[];
  onChange: (cues: VisualCue[]) => void;
  placement: number | null;
  onPlacement: (index: number | null) => void;
  disabled: boolean;
  hasImage: boolean;
  dirty: boolean;
  onSave: () => void;
}) {
  const [newX, setNewX] = useState(""),
    [newY, setNewY] = useState("");
  const coordinateValid = (value: string) =>
    value.trim() !== "" &&
    Number.isFinite(Number(value)) &&
    Number(value) >= 0 &&
    Number(value) <= 100;
  const update = (index: number, values: Partial<VisualCue>) =>
    onChange(cues.map((cue, i) => (i === index ? { ...cue, ...values } : cue)));
  const moveCue = (index: number, direction: number) => {
    const next = [...cues];
    const destination = index + direction;
    if (destination < 0 || destination >= next.length) return;
    [next[index], next[destination]] = [next[destination], next[index]];
    onChange(next);
    onPlacement(null);
  };
  return (
    <fieldset className="visual-story-editor" disabled={disabled}>
      <legend className="sr-only">Visual story cues</legend>
      <div className="visual-story-intro">
        <Film size={19} />
        <h3>Direct the learner’s attention.</h3>
      </div>
      <p className="muted">
        Select up to six source regions. Regions reveal in your authored order
        at evenly spaced intervals, or assign a paragraph for narration timing
        in Guided focus and Whiteboard. Whiteboard keeps earlier regions
        visible, then shows the full original; Studio retains the full slide
        with callouts. Review each label, position, and region against the
        source.
      </p>
      {!hasImage && (
        <p className="muted">Render the slide preview before placing cues.</p>
      )}
      <div className="visual-cue-actions">
        <button
          type="button"
          className="button secondary"
          disabled={cues.length >= 6 || !hasImage || placement === -1}
          onClick={() => {
            setNewX("");
            setNewY("");
            onPlacement(-1);
          }}
        >
          <Plus size={15} />
          Add cue
        </button>
        <span>{cues.length} / 6 cues</span>
      </div>
      {placement !== null && (
        <div className="cue-placement-help" role="status">
          <p>
            {placement === -1
              ? "Click a point on the slide to place your new cue, or enter its coordinates below."
              : `Click the slide to reposition cue ${placement + 1}, or edit its coordinates below.`}
          </p>
          <button
            type="button"
            className="text-button"
            onClick={() => onPlacement(null)}
          >
            Cancel positioning
          </button>
          {placement === -1 && (
            <>
              <div className="cue-coordinate-fields">
                <label>
                  Horizontal %
                  <input
                    type="number"
                    min="0"
                    max="100"
                    step="0.1"
                    value={newX}
                    onChange={(e) => setNewX(e.target.value)}
                    placeholder="0–100"
                  />
                </label>
                <label>
                  Vertical %
                  <input
                    type="number"
                    min="0"
                    max="100"
                    step="0.1"
                    value={newY}
                    onChange={(e) => setNewY(e.target.value)}
                    placeholder="0–100"
                  />
                </label>
              </div>
              <button
                type="button"
                className="button secondary"
                disabled={
                  !coordinateValid(newX) ||
                  !coordinateValid(newY) ||
                  cues.length >= 6
                }
                onClick={() => {
                  onChange([
                    ...cues,
                    {
                      label: "",
                      x: Number(newX) / 100,
                      y: Number(newY) / 100,
                      width: 0.24,
                      height: 0.24,
                    },
                  ]);
                  onPlacement(null);
                }}
              >
                Add at coordinates
              </button>
            </>
          )}
        </div>
      )}
      <ol className="visual-cue-list">
        {cues.map((cue, index) => (
          <li key={index} className={placement === index ? "selected" : ""}>
            <div className="visual-cue-heading">
              <strong>Cue {index + 1}</strong>
              <div className="cue-order-controls">
                <button
                  type="button"
                  className="icon-button"
                  disabled={index === 0}
                  aria-label={`Move cue ${index + 1} earlier`}
                  onClick={() => moveCue(index, -1)}
                >
                  <ChevronLeft size={15} />
                </button>
                <button
                  type="button"
                  className="icon-button"
                  disabled={index === cues.length - 1}
                  aria-label={`Move cue ${index + 1} later`}
                  onClick={() => moveCue(index, 1)}
                >
                  <ChevronRight size={15} />
                </button>
                <button
                  type="button"
                  className="icon-button"
                  aria-label={`Remove cue ${index + 1}`}
                  onClick={() => {
                    onChange(cues.filter((_, i) => i !== index));
                    onPlacement(null);
                  }}
                >
                  <X size={15} />
                </button>
              </div>
            </div>
            <label>
              Source-grounded label
              <input
                maxLength={CUE_LABEL_LIMIT}
                value={cue.label}
                onChange={(e) => update(index, { label: e.target.value })}
                placeholder="Name the feature or explain its role"
                aria-invalid={!cue.label.trim()}
              />
              <span className="cue-label-count">
                {cue.label.length} / {CUE_LABEL_LIMIT}
              </span>
            </label>
            <label>
              Start with narration paragraph
              <select
                value={cue.paragraph ?? "auto"}
                onChange={(event) =>
                  update(index, {
                    paragraph:
                      event.target.value === "auto"
                        ? undefined
                        : Number(event.target.value),
                  })
                }
              >
                <option value="auto">Automatic spacing</option>
                {paragraphs.map((paragraph, paragraphIndex) => (
                  <option key={paragraphIndex} value={paragraphIndex}>
                    {paragraphIndex + 1}. {paragraph.slice(0, 75)}
                    {paragraph.length > 75 ? "…" : ""}
                  </option>
                ))}
              </select>
            </label>
            <div className="cue-coordinate-fields">
              <label>
                Horizontal %
                <input
                  type="number"
                  min="0"
                  max="100"
                  step="0.1"
                  value={Math.round(cue.x * 1000) / 10}
                  onChange={(e) => {
                    const value = e.target.valueAsNumber;
                    if (Number.isFinite(value))
                      update(index, {
                        x: Math.max(0, Math.min(100, value)) / 100,
                      });
                  }}
                />
              </label>
              <label>
                Vertical %
                <input
                  type="number"
                  min="0"
                  max="100"
                  step="0.1"
                  value={Math.round(cue.y * 1000) / 10}
                  onChange={(e) => {
                    const value = e.target.valueAsNumber;
                    if (Number.isFinite(value))
                      update(index, {
                        y: Math.max(0, Math.min(100, value)) / 100,
                      });
                  }}
                />
              </label>
            </div>
            <div className="cue-coordinate-fields">
              <label>
                Region width %
                <input
                  type="number"
                  min="2"
                  max="100"
                  step="1"
                  value={Math.round((cue.width ?? 0.24) * 1000) / 10}
                  onChange={(e) => {
                    const value = e.target.valueAsNumber;
                    if (Number.isFinite(value))
                      update(index, {
                        width: Math.max(2, Math.min(100, value)) / 100,
                      });
                  }}
                />
              </label>
              <label>
                Region height %
                <input
                  type="number"
                  min="2"
                  max="100"
                  step="1"
                  value={Math.round((cue.height ?? 0.24) * 1000) / 10}
                  onChange={(e) => {
                    const value = e.target.valueAsNumber;
                    if (Number.isFinite(value))
                      update(index, {
                        height: Math.max(2, Math.min(100, value)) / 100,
                      });
                  }}
                />
              </label>
            </div>
            <button
              type="button"
              className="text-button"
              disabled={!hasImage}
              onClick={() => onPlacement(index)}
            >
              Reposition on slide
            </button>
          </li>
        ))}
      </ol>
      {!cues.length && (
        <p className="cue-empty">
          No cues yet. Your original visual stays intact.
        </p>
      )}
      <p className="muted">
        Horizontal and vertical values set the region center from the image’s
        top-left corner. Outlines show the selected area, clipped at image
        edges. Without cues, Whiteboard shows the full source visual.
      </p>
      <button
        type="button"
        className="button primary full"
        disabled={!dirty || cues.some((cue) => !cue.label.trim())}
        onClick={onSave}
      >
        Save visual story
      </button>
      {cues.some((cue) => !cue.label.trim()) && (
        <p className="muted" role="status">
          Add a label to every cue before saving.
        </p>
      )}
    </fieldset>
  );
}

function VoiceControls({
  health,
  engine,
  voice,
  delivery,
  rate,
  disabled,
  onEngine,
  onVoice,
  onDelivery,
  onRate,
}: {
  health: Health | null;
  engine: string;
  voice: string;
  delivery: "warm" | "clear" | "engaging";
  rate: number;
  disabled: boolean;
  onEngine: (value: string) => void;
  onVoice: (value: string) => void;
  onDelivery: (value: "warm" | "clear" | "engaging") => void;
  onRate: (value: number) => void;
}) {
  const [preview, setPreview] = useState<{ key: string; url: string } | null>(
    null,
  );
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState("");
  const request = useRef<AbortController | null>(null);
  const previewKey = `${engine}:${voice}:${rate}:${delivery}`;
  useEffect(() => {
    request.current?.abort();
    request.current = null;
    setPreviewLoading(false);
    setPreviewError("");
    return () => {
      request.current?.abort();
      request.current = null;
    };
  }, [previewKey]);
  const audition = async () => {
    if (request.current || disabled || !voiceReady(health, engine)) return;
    const controller = new AbortController();
    request.current = controller;
    setPreviewLoading(true);
    setPreviewError("");
    setPreview(null);
    try {
      const result = await api<{ url: string }>("/voice-preview", {
        method: "POST",
        body: JSON.stringify({ engine, voice, rate, delivery }),
        signal: controller.signal,
      });
      if (request.current !== controller) return;
      if (!result.url.startsWith("/api/voice-previews/"))
        throw new Error(
          "The voice preview returned an invalid audio location.",
        );
      setPreview({ key: previewKey, url: result.url });
    } catch (error) {
      if (request.current === controller && !controller.signal.aborted)
        setPreviewError(
          error instanceof Error
            ? error.message
            : "Could not generate the voice preview. Please try again.",
        );
    } finally {
      if (request.current === controller) {
        request.current = null;
        setPreviewLoading(false);
      }
    }
  };
  return (
    <div className="voice-controls">
      <label>
        Voice engine
        <select
          value={engine}
          disabled={disabled}
          onChange={(event) => onEngine(event.target.value)}
        >
          <option value="qwen" disabled={!health?.qwen_tts}>
            Qwen · expressive local voice
          </option>
          <option value="kokoro" disabled={!health?.kokoro}>
            Kokoro · expressive narration
          </option>
          <option value="piper" disabled={!health?.piper}>
            Piper · compact English voice
          </option>
          <option value="windows" disabled={!health?.windows_voice}>
            Windows · system voice
          </option>
        </select>
      </label>
      {engine === "qwen" && (
        <>
          <label>
            Narrator voice
            <select
              value={voice}
              disabled={disabled}
              onChange={(event) => onVoice(event.target.value)}
            >
              <option value="Aiden">Aiden</option>
              <option value="Ryan">Ryan</option>
            </select>
          </label>
          <label>
            Voice delivery
            <select
              value={delivery}
              disabled={disabled}
              onChange={(event) =>
                onDelivery(event.target.value as "warm" | "clear" | "engaging")
              }
            >
              <option value="warm">Warm</option>
              <option value="clear">Clear</option>
              <option value="engaging">Engaging</option>
            </select>
          </label>
          <p className="voice-delivery-help">
            Delivery guides the local voice. Audition the sample, then listen to
            medical terms and pacing in the final lesson.
          </p>
        </>
      )}
      {engine === "kokoro" && (
        <label>
          Narrator voice
          <select
            value={voice}
            disabled={disabled}
            onChange={(event) => onVoice(event.target.value)}
          >
            {VOICES.map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
      )}
      <label>
        Narration pace{" "}
        <span className="voice-rate">
          {engine === "qwen"
            ? rate < 0.95
              ? "Slower"
              : rate > 1.05
                ? "Brisk"
                : "Natural"
            : `${rate.toFixed(2)}×`}
        </span>
        <input
          type="range"
          min="0.7"
          max="1.4"
          step="0.05"
          value={rate}
          disabled={disabled}
          aria-valuetext={
            engine === "qwen"
              ? rate < 0.95
                ? "Slower delivery guidance"
                : rate > 1.05
                  ? "Brisk delivery guidance"
                  : "Natural delivery guidance"
              : `${rate.toFixed(2)} times normal speed`
          }
          onChange={(event) => onRate(Number(event.target.value))}
        />
      </label>
      <div className="voice-audition" aria-busy={previewLoading}>
        <button
          type="button"
          className="button secondary"
          disabled={disabled || previewLoading || !voiceReady(health, engine)}
          onClick={() => void audition()}
        >
          {previewLoading ? (
            <LoaderCircle className="spin" size={16} />
          ) : (
            <AudioLines size={16} />
          )}
          {previewLoading ? "Preparing preview…" : "Preview voice"}
        </button>
        <p className="muted">
          Listen to a short sample before exporting. Uses a fixed, nonmedical
          script processed on your device.
        </p>
        {previewLoading && (
          <p className="muted" role="status">
            Generating your voice sample. This may take a few moments.
          </p>
        )}
        {previewError && (
          <p className="voice-preview-error" role="alert">
            {previewError}
          </p>
        )}
        {preview?.key === previewKey && (
          <div className="voice-preview-player">
            <p className="muted" role="status">
              Sample ready. Press play to listen.
            </p>
            <audio
              key={preview.url}
              controls
              preload="metadata"
              src={preview.url}
              aria-label="Narrator voice sample"
              onError={() =>
                setPreviewError(
                  "The audio could not be loaded. Try generating the preview again.",
                )
              }
            >
              Your browser does not support audio playback.
            </audio>
          </div>
        )}
      </div>
    </div>
  );
}

function ProjectSettings({
  project,
  onSave,
  onError,
}: {
  project: Project;
  onSave: (p: Project) => void;
  onError: (e: string) => void;
}) {
  const [name, setName] = useState(project.name),
    [audience, setAudience] = useState(project.audience),
    [specialty, setSpecialty] = useState(project.specialty),
    [saving, setSaving] = useState(false),
    [saved, setSaved] = useState(false);
  return (
    <form
      onSubmit={async (e) => {
        e.preventDefault();
        if (saving) return;
        setSaving(true);
        setSaved(false);
        onError("");
        try {
          onSave(
            await api<Project>(`/projects/${project.id}`, {
              method: "PATCH",
              body: JSON.stringify({ name, audience, specialty }),
            }),
          );
          setSaved(true);
        } catch (err) {
          onError((err as Error).message);
        } finally {
          setSaving(false);
        }
      }}
    >
      <label>
        Presentation name
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          required
        />
      </label>
      <label>
        Medical specialty
        <input
          value={specialty}
          onChange={(e) => setSpecialty(e.target.value)}
          required
        />
      </label>
      <label>
        Learner audience
        <input
          value={audience}
          onChange={(e) => setAudience(e.target.value)}
          required
        />
      </label>
      <button className="button secondary" disabled={saving || busy(project)}>
        {saving ? "Saving…" : "Save presentation details"}
      </button>
      {saved && (
        <p role="status" className="muted">
          Presentation details saved.
        </p>
      )}
    </form>
  );
}
createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
