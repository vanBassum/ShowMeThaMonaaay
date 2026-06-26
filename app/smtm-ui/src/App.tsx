import { AppShell } from "@/components/shell/AppShell"
import { ServerStateProvider } from "@/lib/server-state"

export function App() {
  return (
    <ServerStateProvider>
      <AppShell />
    </ServerStateProvider>
  )
}

export default App
