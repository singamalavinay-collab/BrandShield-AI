import React from 'react';
import { AlertCircle, Info, ShieldAlert, CheckCircle2 } from 'lucide-react';

interface AlertBannerProps {
  type?: 'info' | 'warning' | 'governance' | 'success';
  title?: string;
  children: React.ReactNode;
  className?: string;
}

export const AlertBanner: React.FC<AlertBannerProps> = ({
  type = 'info',
  title,
  children,
  className = '',
}) => {
  let containerStyles = 'bg-blue-50 border-blue-200 text-blue-900';
  let Icon = Info;
  let iconColor = 'text-blue-600';

  if (type === 'governance') {
    containerStyles = 'bg-slate-900 border-slate-800 text-slate-100 shadow-sm';
    Icon = ShieldAlert;
    iconColor = 'text-teal-400';
  } else if (type === 'warning') {
    containerStyles = 'bg-amber-50 border-amber-200 text-amber-900';
    Icon = AlertCircle;
    iconColor = 'text-amber-600';
  } else if (type === 'success') {
    containerStyles = 'bg-emerald-50 border-emerald-200 text-emerald-900';
    Icon = CheckCircle2;
    iconColor = 'text-emerald-600';
  }

  return (
    <div className={`p-4 rounded-lg border text-sm flex items-start gap-3 ${containerStyles} ${className}`}>
      <Icon className={`w-5 h-5 flex-shrink-0 mt-0.5 ${iconColor}`} />
      <div className="flex-1">
        {title && <div className="font-semibold mb-0.5">{title}</div>}
        <div className="leading-relaxed opacity-95">{children}</div>
      </div>
    </div>
  );
};
