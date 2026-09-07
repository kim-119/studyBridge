package com.studybridge.api.service;

import org.springframework.stereotype.Component;
import java.util.*;
import java.util.regex.*;

/** Lower-bound proportional apportionment, with stable largest-remainder rounding. */
@Component
public class PlannerTimeAllocator {
    public Integer target(String value, Integer storedMinutes) {
        if (value == null || value.isBlank()) return storedMinutes != null && storedMinutes > 0 ? storedMinutes : null;
        String s = value.trim(); long minutes;
        if (s.matches("\\d+")) minutes = Long.parseLong(s);
        else if (s.matches("\\d+:[0-5]\\d")) {
            String[] parts=s.split(":"); minutes=Long.parseLong(parts[0])*60+Long.parseLong(parts[1]);
        } else {
            Matcher m=Pattern.compile("(?:(\\d+)\\s*시간)?\\s*(?:(\\d+)\\s*분)?").matcher(s);
            if (!m.matches() || (m.group(1)==null && m.group(2)==null))
                throw new IllegalArgumentException("목표시간을 분, H:MM 또는 N시간 M분 형식으로 입력해 주세요.");
            minutes=(m.group(1)==null?0:Long.parseLong(m.group(1))*60)+(m.group(2)==null?0:Long.parseLong(m.group(2)));
        }
        if(minutes<1 || minutes>10080) throw new IllegalArgumentException("목표시간은 1분 이상 10080분 이하여야 합니다.");
        return (int)minutes;
    }
    public List<Integer> normalize(List<Integer> proposed, Integer target) {
        if(proposed==null || proposed.isEmpty()) throw new IllegalArgumentException("시간을 배정할 Task가 없습니다.");
        int n=proposed.size(); long sum=0; long[] weights=new long[n];
        for(int i=0;i<n;i++){ weights[i]=Math.max(1,proposed.get(i)==null?1:proposed.get(i)); sum+=weights[i]; }
        if(target==null) {
            if(sum>10080) throw new IllegalArgumentException("AI 예상 학습시간이 허용 범위를 초과했습니다.");
            return Arrays.stream(weights).mapToObj(Math::toIntExact).toList();
        }
        if(target<n) throw new IllegalArgumentException("목표시간이 Task 수보다 적어 각 Task에 최소 1분을 배정할 수 없습니다.");
        if(target>10080) throw new IllegalArgumentException("목표시간이 허용 범위를 초과했습니다.");
        int[] result=new int[n]; boolean[] fixed=new boolean[n]; int remaining=target; long denominator=sum;
        boolean changed;
        do {
            changed=false;
            for(int i=0;i<n;i++) if(!fixed[i] && weights[i]*remaining<denominator){
                fixed[i]=true;result[i]=1;remaining--;denominator-=weights[i];changed=true;
            }
        } while(changed);
        long[] remainders=new long[n]; int assigned=0;
        for(int i=0;i<n;i++) if(!fixed[i]) {
            long scaled=weights[i]*remaining;result[i]=(int)(scaled/denominator);remainders[i]=scaled%denominator;assigned+=result[i];
        }
        List<Integer> order=new ArrayList<>();for(int i=0;i<n;i++)if(!fixed[i])order.add(i);
        order.sort(Comparator.<Integer>comparingLong(i->remainders[i]).reversed().thenComparingInt(i->i));
        for(int i=0;i<remaining-assigned;i++)result[order.get(i)]++;
        return Arrays.stream(result).boxed().toList();
    }
}
