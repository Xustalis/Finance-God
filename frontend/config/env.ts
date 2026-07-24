export function resolveWorkbenchOrigin(env:Record<string,string|undefined>):string{return env.VITE_WORKBENCH_ORIGIN||env.WORKBENCH_ORIGIN||''}
