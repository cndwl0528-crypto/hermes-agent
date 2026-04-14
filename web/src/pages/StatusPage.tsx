import { useEffect, useState } from "react";
import {
  Activity,
  AlertTriangle,
  ArrowUpRight,
  Clock,
  Cpu,
  Database,
  Radio,
  Wifi,
  WifiOff,
} from "lucide-react";
import { api } from "@/lib/api";
import type { PlatformStatus, ProjectOpsSummary, SessionInfo, StatusResponse } from "@/lib/api";
import { timeAgo, isoTimeAgo } from "@/lib/utils";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

const PLATFORM_STATE_BADGE: Record<string, { variant: "success" | "warning" | "destructive"; label: string }> = {
  connected: { variant: "success", label: "Connected" },
  disconnected: { variant: "warning", label: "Disconnected" },
  fatal: { variant: "destructive", label: "Error" },
};

const GATEWAY_STATE_DISPLAY: Record<string, { badge: "success" | "warning" | "destructive" | "outline"; label: string }> = {
  running: { badge: "success", label: "Running" },
  starting: { badge: "warning", label: "Starting" },
  startup_failed: { badge: "destructive", label: "Failed" },
  stopped: { badge: "outline", label: "Stopped" },
};

function gatewayValue(status: StatusResponse): string {
  if (status.gateway_running) return `PID ${status.gateway_pid}`;
  if (status.gateway_state === "startup_failed") return "Start failed";
  return "Not running";
}

function gatewayBadge(status: StatusResponse) {
  const info = status.gateway_state ? GATEWAY_STATE_DISPLAY[status.gateway_state] : null;
  if (info) return info;
  return status.gateway_running
    ? { badge: "success" as const, label: "Running" }
    : { badge: "outline" as const, label: "Off" };
}

export default function StatusPage() {
  const [status, setStatus] = useState<StatusResponse | null>(null);
  const [projectOps, setProjectOps] = useState<ProjectOpsSummary[]>([]);
  const [sessions, setSessions] = useState<SessionInfo[]>([]);

  useEffect(() => {
    const load = () => {
      api.getStatus().then(setStatus).catch(() => {});
      api.getProjectOpsProjects()
        .then((resp) => setProjectOps(resp.projects || []))
        .catch(() => {
          api.getProjectOpsSummary()
            .then((resp) => setProjectOps(resp ? [resp] : []))
            .catch(() => {});
        });
      api.getSessions(50).then((resp) => setSessions(resp.sessions)).catch(() => {});
    };
    load();
    const interval = setInterval(load, 5000);
    return () => clearInterval(interval);
  }, []);

  if (!status) {
    return (
      <div className="flex items-center justify-center py-24">
        <div className="h-6 w-6 animate-spin rounded-full border-2 border-primary border-t-transparent" />
      </div>
    );
  }

  const gwBadge = gatewayBadge(status);

  const items = [
    {
      icon: Cpu,
      label: "Agent",
      value: `v${status.version}`,
      badgeText: "Live",
      badgeVariant: "success" as const,
    },
    {
      icon: Radio,
      label: "Gateway",
      value: gatewayValue(status),
      badgeText: gwBadge.label,
      badgeVariant: gwBadge.badge,
    },
    {
      icon: Activity,
      label: "Active Sessions",
      value: status.active_sessions > 0 ? `${status.active_sessions} running` : "None",
      badgeText: status.active_sessions > 0 ? "Live" : "Off",
      badgeVariant: (status.active_sessions > 0 ? "success" : "outline") as "success" | "outline",
    },
  ];

  const platforms = Object.entries(status.gateway_platforms ?? {});
  const activeSessions = sessions.filter((s) => s.is_active);
  const recentSessions = sessions.filter((s) => !s.is_active).slice(0, 5);

  // Collect alerts that need attention
  const alerts: { message: string; detail?: string }[] = [];
  if (status.gateway_state === "startup_failed") {
    alerts.push({
      message: "Gateway failed to start",
      detail: status.gateway_exit_reason ?? undefined,
    });
  }
  const failedPlatforms = platforms.filter(([, info]) => info.state === "fatal" || info.state === "disconnected");
  for (const [name, info] of failedPlatforms) {
    alerts.push({
      message: `${name.charAt(0).toUpperCase() + name.slice(1)} ${info.state === "fatal" ? "error" : "disconnected"}`,
      detail: info.error_message ?? undefined,
    });
  }


  return (
    <div className="flex flex-col gap-6">
      {/* Alert banner — breaks grid monotony for critical states */}
      {alerts.length > 0 && (
        <div className="border border-destructive/30 bg-destructive/[0.06] p-4">
          <div className="flex items-start gap-3">
            <AlertTriangle className="h-5 w-5 text-destructive shrink-0 mt-0.5" />
            <div className="flex flex-col gap-2 min-w-0">
              {alerts.map((alert, i) => (
                <div key={i}>
                  <p className="text-sm font-medium text-destructive">{alert.message}</p>
                  {alert.detail && (
                    <p className="text-xs text-destructive/70 mt-0.5">{alert.detail}</p>
                  )}
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      <div className="grid gap-4 sm:grid-cols-3">
        {items.map(({ icon: Icon, label, value, badgeText, badgeVariant }) => (
          <Card key={label}>
            <CardHeader className="flex flex-row items-center justify-between pb-2">
              <CardTitle className="text-sm font-medium">{label}</CardTitle>
              <Icon className="h-4 w-4 text-muted-foreground" />
            </CardHeader>

            <CardContent>
              <div className="text-2xl font-bold font-display">{value}</div>

              {badgeText && (
                <Badge variant={badgeVariant} className="mt-2">
                  {badgeVariant === "success" && (
                    <span className="mr-1 inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-current" />
                  )}
                  {badgeText}
                </Badge>
              )}
            </CardContent>
          </Card>
        ))}
      </div>

      <ProjectOpsLauncher projectOps={projectOps} />

      {platforms.length > 0 && (
        <PlatformsCard platforms={platforms} />
      )}

      {activeSessions.length > 0 && (
        <Card>
          <CardHeader>
            <div className="flex items-center gap-2">
              <Activity className="h-5 w-5 text-success" />
              <CardTitle className="text-base">Active Sessions</CardTitle>
            </div>
          </CardHeader>

          <CardContent className="grid gap-3">
            {activeSessions.map((s) => (
              <div
                key={s.id}
                className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2 border border-border p-3 w-full"
              >
                <div className="flex flex-col gap-1 min-w-0 w-full">
                  <div className="flex items-center gap-2">
                    <span className="font-medium text-sm truncate">{s.title ?? "Untitled"}</span>

                    <Badge variant="success" className="text-[10px] shrink-0">
                      <span className="mr-1 inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-current" />
                      Live
                    </Badge>
                  </div>

                  <span className="text-xs text-muted-foreground truncate">
                    <span className="font-mono-ui">{(s.model ?? "unknown").split("/").pop()}</span> · {s.message_count} msgs · {timeAgo(s.last_active)}
                  </span>
                </div>
              </div>
            ))}
          </CardContent>
        </Card>
      )}

      {recentSessions.length > 0 && (
        <Card>
          <CardHeader>
            <div className="flex items-center gap-2">
              <Clock className="h-5 w-5 text-muted-foreground" />
              <CardTitle className="text-base">Recent Sessions</CardTitle>
            </div>
          </CardHeader>

          <CardContent className="grid gap-3">
            {recentSessions.map((s) => (
              <div
                key={s.id}
                className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2 border border-border p-3 w-full"
              >
                <div className="flex flex-col gap-1 min-w-0 w-full">
                  <span className="font-medium text-sm truncate">{s.title ?? "Untitled"}</span>

                  <span className="text-xs text-muted-foreground truncate">
                    <span className="font-mono-ui">{(s.model ?? "unknown").split("/").pop()}</span> · {s.message_count} msgs · {timeAgo(s.last_active)}
                  </span>

                  {s.preview && (
                    <span className="text-xs text-muted-foreground/70 truncate">
                      {s.preview}
                    </span>
                  )}
                </div>

                <Badge variant="outline" className="text-[10px] shrink-0 self-start sm:self-center">
                  <Database className="mr-1 h-3 w-3" />
                  {s.source ?? "local"}
                </Badge>
              </div>
            ))}
          </CardContent>
        </Card>
      )}
    </div>
  );
}

function ProjectOpsLauncher({ projectOps }: { projectOps: ProjectOpsSummary[] }) {
  const hasProjects = projectOps.length > 0;

  return (
    <Card>
      <CardHeader>
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div className="flex flex-col gap-1">
            <div className="flex items-center gap-2">
              <Database className="h-5 w-5 text-muted-foreground" />
              <CardTitle className="text-base">Project Ops</CardTitle>
            </div>
            <p className="text-xs text-muted-foreground">
              프로젝트별 작전실 모음 / project ops launcher
            </p>
            <p className="text-xs text-muted-foreground/70">
              Internal names: Super Mario Dashboard · project ops launcher · next-run attach
            </p>
          </div>

          {hasProjects ? (
            <Badge variant="outline" className="self-start text-[10px]">
              {projectOps.length} projects
            </Badge>
          ) : null}
        </div>
      </CardHeader>

      <CardContent className="grid gap-4">
        {!hasProjects ? (
          <div className="border border-border bg-background/20 p-4 text-sm text-muted-foreground">
            등록된 프로젝트가 아직 없습니다. 기본값으로는 `hi-alice`를 찾고, 여러 프로젝트를 쓰려면 `~/.hermes/project-ops.json` 또는 `HERMES_PROJECT_OPS_PROJECTS`를 채우면 됩니다.
          </div>
        ) : (
          <div className="grid gap-4 xl:grid-cols-2">
            {projectOps.map((project) => (
              <ProjectOpsProjectCard key={project.project_name} project={project} />
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function ProjectOpsProjectCard({ project }: { project: ProjectOpsSummary }) {
  return (
    <div className="border border-border bg-background/20 p-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <p className="text-sm font-semibold">{project.label || project.project_name}</p>
            <Badge variant={project.available ? "success" : "warning"} className="text-[10px]">
              {project.available ? "Connected" : "Needs setup"}
            </Badge>
          </div>
          <p className="mt-1 text-xs text-muted-foreground">
            {project.description || "프로젝트 운영 상태를 여는 작전실 카드입니다."}
          </p>
          <p className="mt-1 text-xs text-muted-foreground/70">
            Internal names: {project.project_name} · Super Mario Dashboard
          </p>
        </div>

        {project.dashboard_url ? (
          <a
            href={project.dashboard_url}
            target="_blank"
            rel="noreferrer"
            className="inline-flex h-8 items-center gap-2 self-start border border-border px-3 text-[0.65rem] font-display uppercase tracking-[0.1em] text-foreground transition-colors hover:bg-foreground/10"
          >
            Open Ops
            <ArrowUpRight className="h-3.5 w-3.5" />
          </a>
        ) : null}
      </div>

      <div className="mt-4 grid gap-3 sm:grid-cols-4">
        <ProjectOpsMetric
          label="Open Work"
          value={`${project.active_count || 0}`}
          note="currently active"
        />
        <ProjectOpsMetric
          label="Carry Forward"
          value={`${project.carry_forward_count || 0}`}
          note="needs follow-up"
          tone={project.carry_forward_count > 0 ? "warning" : "default"}
        />
        <ProjectOpsMetric
          label="Attach Review"
          value={`${project.attach_pending_count || 0}`}
          note="human check needed"
          tone={project.attach_pending_count > 0 ? "warning" : "default"}
        />
        <ProjectOpsMetric
          label="Bridge"
          value={project.bridge_status || "unknown"}
          note="cross-host handoff"
          tone={project.bridge_status === "failed" ? "destructive" : "default"}
        />
      </div>

      <div className="mt-3 flex flex-col gap-1 border border-border bg-background/20 p-3">
        <p className="text-sm font-medium">
          {project.latest_task_title || "최근 작업 기록이 없습니다."}
        </p>
        <p className="text-xs text-muted-foreground">
          {project.latest_task_id
            ? `${project.latest_task_id} · selected attach ${project.attach_selected_count}`
            : `selected attach ${project.attach_selected_count || 0}`}
        </p>
        {project.bridge_last_error ? (
          <p className="text-xs text-warning">{project.bridge_last_error}</p>
        ) : (
          <p className="text-xs text-muted-foreground/70">
            root: <span className="font-mono-ui">{project.project_root}</span>
          </p>
        )}
      </div>
    </div>
  );
}

function ProjectOpsMetric({
  label,
  value,
  note,
  tone = "default",
}: {
  label: string;
  value: string;
  note: string;
  tone?: "default" | "warning" | "destructive";
}) {
  const toneClass = tone === "warning"
    ? "text-warning"
    : tone === "destructive"
      ? "text-destructive"
      : "text-foreground";

  return (
    <div className="border border-border bg-background/20 p-3">
      <p className="text-[0.65rem] font-display uppercase tracking-[0.1em] text-muted-foreground">
        {label}
      </p>
      <p className={`mt-1 text-xl font-bold ${toneClass}`}>{value}</p>
      <p className="mt-1 text-xs text-muted-foreground">{note}</p>
    </div>
  );
}

function PlatformsCard({ platforms }: PlatformsCardProps) {
  return (
    <Card>
      <CardHeader>
        <div className="flex items-center gap-2">
          <Radio className="h-5 w-5 text-muted-foreground" />
          <CardTitle className="text-base">Connected Platforms</CardTitle>
        </div>
      </CardHeader>

      <CardContent className="grid gap-3">
        {platforms.map(([name, info]) => {
          const display = PLATFORM_STATE_BADGE[info.state] ?? {
            variant: "outline" as const,
            label: info.state,
          };
          const IconComponent = info.state === "connected" ? Wifi : info.state === "fatal" ? AlertTriangle : WifiOff;

          return (
            <div
              key={name}
              className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2 border border-border p-3 w-full"
            >
              <div className="flex items-center gap-3 min-w-0 w-full">
                <IconComponent className={`h-4 w-4 shrink-0 ${
                  info.state === "connected"
                    ? "text-success"
                    : info.state === "fatal"
                      ? "text-destructive"
                      : "text-warning"
                }`} />

                <div className="flex flex-col gap-0.5 min-w-0">
                  <span className="text-sm font-medium capitalize truncate">{name}</span>

                  {info.error_message && (
                    <span className="text-xs text-destructive">{info.error_message}</span>
                  )}

                  {info.updated_at && (
                    <span className="text-xs text-muted-foreground">
                      Last update: {isoTimeAgo(info.updated_at)}
                    </span>
                  )}
                </div>
              </div>

              <Badge variant={display.variant} className="shrink-0 self-start sm:self-center">
                {display.variant === "success" && (
                  <span className="mr-1 inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-current" />
                )}
                {display.label}
              </Badge>
            </div>
          );
        })}
      </CardContent>
    </Card>
  );
}

interface PlatformsCardProps {
  platforms: [string, PlatformStatus][];
}
