import { useEffect, useMemo, useState } from "react";

import {
  Button,
  type ButtonProps,
  Dialog,
  DialogCloseButton,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTitleExtra,
  DialogTrigger,
  Flex,
  Icon,
  Icons,
  Input,
  Label,
  ListBox,
  Loading,
  Modal,
  ModalOverlay,
  Popover,
  Select,
  SelectChevronUpDownIcon,
  SelectItem,
  SelectValue,
  Text,
  TextField,
  View,
} from "@phoenix/components";
import { useNotifyError, useNotifySuccess } from "@phoenix/contexts";
import { useDatasetContext } from "@phoenix/contexts/DatasetContext";
import { prependBasename } from "@phoenix/utils/routingUtils";

type ExperimentScript = {
  key: string;
  label: string;
  description: string;
};

type RunExperimentResponse = {
  jobId: string;
  status: string;
  logUrl: string;
  statusUrl: string;
};

async function fetchExperimentScripts(): Promise<ExperimentScript[]> {
  const response = await fetch(prependBasename("/v1/experiment-scripts"));
  if (!response.ok) {
    throw new Error("Failed to load experiment scripts");
  }
  const data = await response.json();
  return data?.data ?? [];
}

interface RunExperimentDialogProps {
  close: () => void;
}

function RunExperimentDialog({ close }: RunExperimentDialogProps) {
  const [scripts, setScripts] = useState<ExperimentScript[]>([]);
  const [isLoadingScripts, setIsLoadingScripts] = useState(true);
  const [scriptsError, setScriptsError] = useState<string | null>(null);
  const [selectedScript, setSelectedScript] = useState<string | null>(null);
  const [experimentName, setExperimentName] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  const datasetId = useDatasetContext((state) => state.datasetId);
  const datasetName = useDatasetContext((state) => state.datasetName);

  const notifySuccess = useNotifySuccess();
  const notifyError = useNotifyError();

  useEffect(() => {
    let isMounted = true;
    const loadScripts = async () => {
      try {
        setIsLoadingScripts(true);
        const scriptList = await fetchExperimentScripts();
        if (!isMounted) {
          return;
        }
        setScripts(scriptList);
        if (scriptList.length > 0) {
          setSelectedScript(scriptList[0]?.key ?? null);
        }
        setScriptsError(null);
      } catch (error) {
        if (!isMounted) {
          return;
        }
        setScriptsError(
          error instanceof Error ? error.message : "Failed to load scripts."
        );
      } finally {
        if (isMounted) {
          setIsLoadingScripts(false);
        }
      }
    };
    loadScripts();
    return () => {
      isMounted = false;
    };
  }, []);

  const scriptOptions = useMemo(() => {
    return scripts.map((script) => ({
      key: script.key,
      label: script.label,
      description: script.description,
    }));
  }, [scripts]);

  const onSubmit = async () => {
    if (!selectedScript) {
      notifyError({
        title: "No script selected",
        message: "Please choose an experiment script before running.",
      });
      return;
    }
    setIsSubmitting(true);
    try {
      const payload: Record<string, unknown> = {
        scriptKey: selectedScript,
      };
      const trimmedName = experimentName.trim();
      if (trimmedName.length > 0) {
        payload.experimentName = trimmedName;
      }
      const response = await fetch(
        prependBasename(`/v1/datasets/${datasetId}/run-experiment`),
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify(payload),
        }
      );
      if (!response.ok) {
        const errorText = await response.text();
        throw new Error(errorText || "Failed to start experiment");
      }
      const data = (await response.json()) as RunExperimentResponse;
      const logUrl = prependBasename(data.logUrl);
      notifySuccess({
        title: "Experiment started",
        message: `Job ${data.jobId} queued for dataset "${datasetName}".`,
        action: {
          text: "View Log",
          onClick: (closeToast) => {
            window.open(logUrl, "_blank", "noopener,noreferrer");
            closeToast();
          },
        },
      });
      close();
    } catch (error) {
      notifyError({
        title: "Failed to run experiment",
        message:
          error instanceof Error
            ? error.message
            : "Unexpected error starting experiment.",
      });
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <DialogContent>
      <DialogHeader>
        <DialogTitle>Run Experiment</DialogTitle>
        <DialogTitleExtra>
          <DialogCloseButton slot="close" />
        </DialogTitleExtra>
      </DialogHeader>
      <View padding="size-300" width="100%" maxWidth={480}>
        <Flex direction="column" gap="size-200">
          <Text>
            Select a Python experiment runner and execute it against the current
            dataset. Credentials for Dify and evaluators must already be
            configured via environment variables.
          </Text>
          <Flex direction="row" gap="size-50">
            <Text weight="semibold">Dataset:</Text>
            <Text>{datasetName}</Text>
          </Flex>
          {isLoadingScripts ? (
            <Loading />
          ) : scriptsError ? (
            <Text color="danger">{scriptsError}</Text>
          ) : scripts.length === 0 ? (
            <Text color="danger">
              No experiment scripts are available. Add an entry in the Phoenix
              backend to enable this feature.
            </Text>
          ) : (
            <>
              <Select
                selectedKey={selectedScript ?? undefined}
                onSelectionChange={(key) =>
              setSelectedScript(key as string | null)
            }
            placeholder="Select an experiment script"
            aria-label="Experiment script"
              >
                <Label>Experiment Script</Label>
                <Button
                  variant="default"
                  trailingVisual={<SelectChevronUpDownIcon />}
                >
                  <SelectValue />
                </Button>
                <Popover>
                  <ListBox>
                    {scriptOptions.map((option) => (
                      <SelectItem
                        key={option.key}
                        id={option.key}
                        textValue={option.label}
                      >
                        <Flex direction="column" gap="size-50">
                          <Text weight="semibold">{option.label}</Text>
                          <Text color="text-700">{option.description}</Text>
                        </Flex>
                      </SelectItem>
                    ))}
                  </ListBox>
                </Popover>
              </Select>
              <TextField value={experimentName} onChange={setExperimentName}>
                <Label>Experiment Name (optional)</Label>
                <Input placeholder="e.g. improved-retrieval-v2" />
              </TextField>
            </>
          )}
          <Flex direction="row" justifyContent="end" gap="size-100">
            <Button
              variant="default"
              onPress={() => {
                close();
              }}
            >
              Cancel
            </Button>
            <Button
              variant="primary"
              isDisabled={
                isSubmitting ||
                isLoadingScripts ||
                !selectedScript ||
                scripts.length === 0
              }
              onPress={onSubmit}
            >
              {isSubmitting ? "Starting..." : "Run"}
            </Button>
          </Flex>
        </Flex>
      </View>
    </DialogContent>
  );
}

export function RunExperimentButton({
  variant = "default",
}: {
  variant?: ButtonProps["variant"];
}) {
  return (
    <DialogTrigger>
      <Button
        size="S"
        variant={variant}
        leadingVisual={<Icon svg={<Icons.ExperimentOutline />} />}
      >
        Run Experiment
      </Button>
      <ModalOverlay isDismissable>
        <Modal variant="slideover" size="L">
          <Dialog>
            {({ close }) => <RunExperimentDialog close={close} />}
          </Dialog>
        </Modal>
      </ModalOverlay>
    </DialogTrigger>
  );
}
