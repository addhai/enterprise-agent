{{/* =============================================================================
  Helm 辅助模板 (_helpers.tpl)

  命名规范、标签、选择器等可复用片段。
  ============================================================================= */}}

{{/* 展开 chart 名 + 版本组合标签 */}}
{{- define "enterprise-agent.labels" -}}
app.kubernetes.io/name: {{ include "enterprise-agent.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ include "enterprise-agent.chart" . }}
environment: {{ .Values.global.environment }}
{{- end }}

{{- define "enterprise-agent.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "enterprise-agent.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/* Service 选择器 */}}
{{- define "enterprise-agent.selectorLabels" -}}
app.kubernetes.io/name: {{ include "enterprise-agent.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/* 服务账户名 */}}
{{- define "enterprise-agent.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "enterprise-agent.name" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{/* 镜像拉取地址 */}}
{{- define "enterprise-agent.image" -}}
{{- printf "%s:%s" .repository .tag }}
{{- end }}
