import { AppShell } from "@/components/shell/AppShell"
import { FixesProvider } from "@/lib/fixes"
import { ServerStateProvider } from "@/lib/server-state"

export function App() {
  return (
    <ServerStateProvider>
      <FixesProvider>
        <AppShell />
      </FixesProvider>
    </ServerStateProvider>
  )
}

export default App
