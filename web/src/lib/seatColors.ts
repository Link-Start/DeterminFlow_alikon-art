const SEAT_COLORS = [
  { dot: "bg-primary", text: "text-primary", border: "border-primary/30", bg: "bg-primary/5" },
  { dot: "bg-primary", text: "text-primary", border: "border-primary/30", bg: "bg-primary/5" },
  { dot: "bg-info", text: "text-info", border: "border-info/30", bg: "bg-info/5" },
  { dot: "bg-success", text: "text-success", border: "border-success/30", bg: "bg-success/5" },
  { dot: "bg-warning", text: "text-warning", border: "border-warning/30", bg: "bg-warning/5" },
  { dot: "bg-destructive", text: "text-destructive", border: "border-destructive/30", bg: "bg-destructive/5" },
];

export function getSeatColor(seatIndex: number) {
  return SEAT_COLORS[seatIndex % SEAT_COLORS.length];
}
