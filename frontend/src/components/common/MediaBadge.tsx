import React from 'react';
import { FileText, Image as ImageIcon, Mic, Video as VideoIcon, FileCheck } from 'lucide-react';

interface MediaBadgeProps {
  mediaType?: string | null;
  size?: 'sm' | 'md';
  className?: string;
}

export const MediaBadge: React.FC<MediaBadgeProps> = ({
  mediaType = 'text',
  size = 'sm',
  className = '',
}) => {
  const normType = (mediaType || 'text').toLowerCase();
  const sizeClasses = size === 'sm' ? 'px-2 py-0.5 text-[10px]' : 'px-2.5 py-1 text-xs';

  let icon = <FileText className="w-3 h-3" />;
  let colorClasses = 'bg-slate-100 text-slate-700 border-slate-200';
  let label = 'TEXT';

  switch (normType) {
    case 'image':
      icon = <ImageIcon className="w-3 h-3 text-purple-600" />;
      colorClasses = 'bg-purple-50 text-purple-700 border-purple-200';
      label = 'IMAGE';
      break;
    case 'audio':
      icon = <Mic className="w-3 h-3 text-amber-600" />;
      colorClasses = 'bg-amber-50 text-amber-700 border-amber-200';
      label = 'AUDIO';
      break;
    case 'video':
      icon = <VideoIcon className="w-3 h-3 text-rose-600" />;
      colorClasses = 'bg-rose-50 text-rose-700 border-rose-200';
      label = 'VIDEO';
      break;
    case 'document':
      icon = <FileCheck className="w-3 h-3 text-blue-600" />;
      colorClasses = 'bg-blue-50 text-blue-700 border-blue-200';
      label = 'DOC';
      break;
    case 'text':
    default:
      icon = <FileText className="w-3 h-3 text-slate-500" />;
      colorClasses = 'bg-slate-100 text-slate-700 border-slate-200';
      label = 'TEXT';
      break;
  }

  return (
    <span
      className={`inline-flex items-center gap-1 font-semibold rounded uppercase tracking-wider border ${sizeClasses} ${colorClasses} ${className}`}
      title={`Media format: ${normType}`}
    >
      {icon}
      <span>{label}</span>
    </span>
  );
};
