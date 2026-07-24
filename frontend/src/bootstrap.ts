export interface BootstrapOptions{hasToken:boolean;hydrate:()=>Promise<void>;mount:()=>void}
export async function bootstrapApplication(options:BootstrapOptions):Promise<void>{if(options.hasToken){try{await options.hydrate()}catch{/* Authentication state owns cleanup; startup must still render. */}}options.mount()}
