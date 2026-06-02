let tail = Promise.resolve();

export function enqueueAutomation(task) {
  const run = tail.then(task, task);
  tail = run.catch(() => undefined);
  return run;
}
