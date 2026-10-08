using UnrealBuildTool;

public class CampfireProbeEditor : ModuleRules
{
    public CampfireProbeEditor(ReadOnlyTargetRules Target) : base(Target)
    {
        PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;
        PrivateDependencyModuleNames.AddRange(new[] {
            "Core", "CoreUObject", "Engine", "UnrealEd", "BlueprintGraph",
            "KismetCompiler", "ScriptDisassembler", "Json"
        });
    }
}
