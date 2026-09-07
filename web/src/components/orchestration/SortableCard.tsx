import { useSortable } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { GripVertical } from "lucide-react";
import { ReactNode } from "react";

interface SortableCardProps {
  id: string;
  children: ReactNode;
  disabled?: boolean;
  className?: string;
}

export default function SortableCard({ id, children, disabled, className = "" }: SortableCardProps) {
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id, disabled });

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.5 : 1,
    zIndex: isDragging ? 50 : undefined,
  };

  return (
    <div
      ref={setNodeRef}
      style={style}
      className={`bg-secondary/80 border border-border/40 rounded-lg px-3 py-3 flex items-start gap-2 group transition-all duration-200 ${className} ${
        isDragging
          ? "border-primary/60 shadow-lg shadow-primary/10 scale-[0.98]"
          : "hover:border-primary/30"
      }`}
    >
      {!disabled && (
        <button
          {...attributes}
          {...listeners}
          aria-label="拖拽排序"
          className="mt-1 p-1.5 min-w-[44px] min-h-[44px] flex items-center justify-center rounded cursor-grab active:cursor-grabbing text-muted-foreground hover:text-primary hover:bg-primary/10 transition-colors flex-shrink-0"
          tabIndex={-1}
        >
          <GripVertical size={14} aria-hidden="true" />
        </button>
      )}
      <div className="flex-1 min-w-0">{children}</div>
    </div>
  );
}
