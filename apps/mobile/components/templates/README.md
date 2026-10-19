# Screen Templates & Nav Registry

This directory contains four screen templates and the nav registry that let new screens be built in ~30-60 lines and surfaced in the UI without touching `_layout.tsx`.

---

## 1. ListScreen

For any screen that fetches a list, shows loading/empty/error, and optionally supports search and filter chips.

```tsx
// app/voices.tsx  (~35 lines)
import { useCallback } from "react";
import { useSession } from "@/src/shared/auth";
import { ListScreen } from "@/components/templates";
import { listVoices } from "@/lib/api";
import type { Voice } from "@/lib/types";
import { VoiceCard } from "@/components/voices/VoiceCard";

export default function VoicesScreen() {
  const { apiKey } = useSession();
  const token = apiKey ?? undefined;

  const fetcher = useCallback(
    () => listVoices({ token }),
    [token],
  );

  return (
    <ListScreen<Voice>
      fetcher={fetcher}
      keyExtractor={(v) => v.voice_id}
      renderItem={(v) => <VoiceCard voice={v} />}
      title="Voices"
      searchable
      matchItem={(v, q) => (v.name ?? "").toLowerCase().includes(q)}
      emptyTitle="No voices yet"
      emptyBody="Clone your voice to get started."
      emptyActionLabel="Clone Voice"
      onEmptyAction={() => {/* open clone sheet */}}
    />
  );
}
```

### Props

| Prop | Type | Description |
|------|------|-------------|
| `fetcher` | `() => Promise<T[]>` | Memoized fetch function — refresh when token changes |
| `keyExtractor` | `(item, index) => string` | FlatList key |
| `renderItem` | `(item, index) => JSX.Element` | Row renderer |
| `title` | `string?` | Optional screen header |
| `searchable` | `boolean` | Show SearchBar |
| `matchItem` | `(item, query) => boolean` | Filter predicate for search |
| `filterItems` | `FilterItem<F>[]` | Chip filter definitions |
| `activeFilter` | `F` | Currently active filter id |
| `filterItem` | `(item, filterId) => boolean` | Filter predicate for chips |
| `emptyTitle/Body` | `string` | Empty state content |

---

## 2. DetailScreen

For any screen that shows a hero, title, sections, and action buttons.

```tsx
// app/job/[id].tsx  (~45 lines)
import { DetailScreen } from "@/components/templates";
import { Button } from "@/components/ui";
import { JobPoster } from "@/src/shared/media/components/JobPoster";

export default function JobDetailScreen() {
  // ... load job

  return (
    <DetailScreen
      hero={<JobPoster jobId={id} style={{ height: 280 }} />}
      title={job.hook ?? job.job_id}
      subtitle={`State: ${job.state}`}
      sections={[
        { title: "Info", content: <JobInfoCard job={job} /> },
        { title: "Timeline", content: <StageProgress job={job} /> },
      ]}
      actions={[
        <Button key="retry" label="Retry" onPress={handleRetry} variant="secondary" />,
        <Button key="download" label="Download" onPress={handleDownload} />,
      ]}
    />
  );
}
```

---

## 3. FormScreen

For any screen that collects input, validates, and submits.

```tsx
// app/team/invite.tsx  (~45 lines)
import { FormScreen } from "@/components/templates";
import { TextField, SelectField } from "@/components/ui";
import { inviteMember } from "@/lib/api/workspaces";

type Fields = { email: string; role: string };

export default function InviteScreen() {
  return (
    <FormScreen<Fields>
      title="Invite Member"
      initialValues={{ email: "", role: "member" }}
      validate={(v) => {
        const errors: Partial<Record<keyof Fields, string>> = {};
        if (!v.email.includes("@")) errors.email = "Valid email required";
        return errors;
      }}
      onSubmit={async (v) => {
        await inviteMember(workspaceId, { email: v.email, role: v.role as WorkspaceRole });
      }}
      fields={(values, onChange, errors) => (
        <>
          <TextField
            label="Email"
            value={values.email}
            onChangeText={(v) => onChange("email", v)}
            error={errors.email}
            keyboardType="email-address"
            autoCapitalize="none"
          />
          <SelectField
            label="Role"
            value={values.role}
            onChange={(v) => onChange("role", v)}
            options={[
              { value: "member", label: "Member" },
              { value: "admin", label: "Admin" },
            ]}
          />
        </>
      )}
      submitLabel="Send Invite"
      onSuccess={() => router.back()}
    />
  );
}
```

---

## 4. WizardScreen

For multi-step flows with progress indicator, back/next, and per-step validation.

```tsx
// app/studio/new-avatar.tsx  (~60 lines)
import { WizardScreen } from "@/components/templates";

type Values = { imageKey: string; displayName: string };

export default function NewAvatarWizard() {
  return (
    <WizardScreen<Values>
      initialValues={{ imageKey: "", displayName: "" }}
      steps={[
        {
          title: "Upload Photo",
          validate: (v) => v.imageKey ? {} : { imageKey: "Photo required" },
          render: (ctx) => (
            <SelfieUploader
              value={ctx.values.imageKey}
              onChange={(key) => ctx.set("imageKey", key)}
              error={ctx.errors.imageKey}
            />
          ),
        },
        {
          title: "Name Your Avatar",
          render: (ctx) => (
            <TextField
              label="Display Name"
              value={ctx.values.displayName}
              onChangeText={(v) => ctx.set("displayName", v)}
            />
          ),
        },
      ]}
      onComplete={async (v) => {
        await createAvatarFromPhoto({ image_key: v.imageKey, display_name: v.displayName });
      }}
      completeLabel="Create Avatar"
      onSuccess={() => router.back()}
    />
  );
}
```

---

## Nav Registry

Screens self-register in `lib/nav/registry.ts`. The registry drives `<RegistryMenu />`, which renders grouped navigation links without any changes to `_layout.tsx`.

### Register a new screen

```ts
// At the top of the screen file or in lib/nav/registry.ts
import { registerScreen } from "@/lib/nav/registry";

registerScreen({
  route: "/my-new-screen",
  title: "My New Screen",
  subtitle: "One-line description for the menu",
  group: "Core",          // "Core" | "Content" | "Analytics" | "Monetize" | "Workspace" | "Settings" | "Labs"
  groupOrder: 1,          // lower = higher in the group list
  order: 20,              // lower = first within the group
});
```

### Render the menu in a hub screen

```tsx
import { RegistryMenu } from "@/lib/nav/RegistryMenu";

// Show all groups
<RegistryMenu scrollable />

// Show only specific groups
<RegistryMenu groups={["Core", "Analytics"]} />
```

### Use the hook for custom rendering

```tsx
import { useRegistryGroups } from "@/lib/nav/RegistryMenu";

function CustomHub() {
  const groups = useRegistryGroups(["Core"]);
  return groups.map((g) => /* custom render */);
}
```

### Group ordering convention

| Order | Group | Contents |
|-------|-------|----------|
| 1 | Core | Create, studio tools |
| 2 | Content | Publishing, calendar, trends |
| 3 | Analytics | Analytics, performance, leaderboard |
| 4 | Monetize | Wallet, marketplace, clipmarket |
| 5 | Workspace | Team, connections, developer |
| 6 | Settings | Account, privacy, support |
| 99 | Labs | Experimental features |
